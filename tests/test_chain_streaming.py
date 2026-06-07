"""Tests for OpenAICompatibleLLMClient.chat_stream — the SSE parser."""

from __future__ import annotations

import json

import httpx
import pytest

from app.chain.llm_client import OpenAICompatibleLLMClient, StreamChunk
from app.chain.models import ChainLLMConfig


def _sse_frames(*chunks: dict, include_done: bool = True) -> bytes:
    """Build a byte-stream of OpenAI-style SSE frames."""
    parts: list[str] = []
    for ch in chunks:
        parts.append("data: " + json.dumps(ch) + "\n\n")
    if include_done:
        parts.append("data: [DONE]\n\n")
    return "".join(parts).encode("utf-8")


def _mock_transport(body: bytes, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=body,
            headers={"content-type": "text/event-stream"},
        )
    return httpx.MockTransport(handler)


async def test_chat_stream_yields_content_deltas(monkeypatch):
    body = _sse_frames(
        {"choices": [{"delta": {"content": "Hello"}}]},
        {"choices": [{"delta": {"content": " "}}]},
        {"choices": [{"delta": {"content": "world"}, "finish_reason": "stop"}]},
    )

    # Patch httpx.AsyncClient to use our MockTransport.
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = _mock_transport(body)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    cfg = ChainLLMConfig(api_base="http://fake", model="fake")
    client = OpenAICompatibleLLMClient()

    chunks: list[StreamChunk] = []
    async for c in client.chat_stream([{"role": "user", "content": "hi"}], cfg):
        chunks.append(c)

    accumulated = "".join(c.content for c in chunks)
    assert accumulated == "Hello world"
    # Last chunk carries finish_reason.
    assert chunks[-1].finish_reason == "stop"


async def test_chat_stream_handles_missing_done_sentinel(monkeypatch):
    """llama.cpp servers don't always emit a trailing `data: [DONE]` — EOF on
    the aiter_lines loop should terminate cleanly."""
    body = _sse_frames(
        {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
        include_done=False,
    )

    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = _mock_transport(body)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    cfg = ChainLLMConfig(api_base="http://fake", model="fake")
    client = OpenAICompatibleLLMClient()
    chunks = [c async for c in client.chat_stream([{"role": "user", "content": "x"}], cfg)]
    assert "".join(c.content for c in chunks) == "ok"


async def test_chat_stream_ignores_comment_and_malformed_lines(monkeypatch):
    """SSE comments (`:`-prefixed lines) and non-JSON `data:` payloads should
    not crash the parser — they're silently skipped."""
    body = (
        b":heartbeat\n\n"
        b"data: not-json\n\n"
        b'data: {"choices":[{"delta":{"content":"final"}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = _mock_transport(body)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    cfg = ChainLLMConfig(api_base="http://fake", model="fake")
    client = OpenAICompatibleLLMClient()
    chunks = [c async for c in client.chat_stream([{"role": "user", "content": "x"}], cfg)]
    assert "".join(c.content for c in chunks) == "final"


async def test_chat_stream_raises_on_http_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"down")

    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    cfg = ChainLLMConfig(api_base="http://fake", model="fake")
    client = OpenAICompatibleLLMClient()
    with pytest.raises(RuntimeError) as exc:
        async for _ in client.chat_stream([{"role": "user", "content": "x"}], cfg):
            pass
    assert "503" in str(exc.value)


async def test_run_llm_step_emits_chunk_events_to_bus(tmp_path):
    """End-to-end: a no-tool LLM step streams chunks into the EventBus."""
    from app.chain.events import EventBus
    from app.chain.models import (
        Alternative, ChainJobRequest, ChainLLMConfig, ChainStep,
    )
    from app.chain.steps.llm import run_llm_step

    step = ChainStep(name="hi", prompt="Hello {{input}}")
    alt = step.alternatives[0]
    req = ChainJobRequest(
        input="world",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[step],
    )
    bus = EventBus("job-xyz")

    class FakeClient:
        def chat_stream(self, messages, llm_config, tools=None):
            async def gen():
                yield StreamChunk(content="part-A")
                yield StreamChunk(content=" part-B", finish_reason="stop")
            return gen()

    step_dir = tmp_path / "step"
    step_dir.mkdir()
    output, fname, prompt = await run_llm_step(
        step_dir, step, alt, req, FakeClient(), "world", 1,
        event_bus=bus, job_id="job-xyz", invocation=0,
    )
    assert output == "part-A part-B"
    assert fname == "output.txt"
    chunks = [e for e in bus.history() if e.type == "llm_chunk"]
    assert [e.payload["delta"] for e in chunks] == ["part-A", " part-B"]
    # step_input was also emitted with the rendered prompt.
    inputs = [e for e in bus.history() if e.type == "step_input"]
    assert len(inputs) == 1
    assert "world" in inputs[0].payload["rendered_prompt"]


async def test_run_llm_step_sends_structured_messages(tmp_path):
    """When `alt.messages` is set, the step renders each content template and
    sends a real role array (not the single `prompt`), and records role-tagged
    blocks in prompt.txt for the trace."""
    from app.chain.models import (
        Alternative, ChainJobRequest, ChainLLMConfig, ChainStep,
    )
    from app.chain.steps.llm import run_llm_step

    alt = Alternative(messages=[
        {"role": "system", "content": "You are {{var.name}}."},
        {"role": "user", "content": "Earlier: {{input}}"},
        {"role": "user", "content": "Reply now."},
    ])
    step = ChainStep(name="turn", alternatives=[alt])
    req = ChainJobRequest(
        input="hello",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[step],
        variables={"name": "Ada"},
    )

    captured: dict = {}

    class FakeClient:
        def chat_stream(self, messages, llm_config, tools=None):
            captured["messages"] = messages

            async def gen():
                yield StreamChunk(content="ok", finish_reason="stop")
            return gen()

    step_dir = tmp_path / "step"
    step_dir.mkdir()
    output, fname, prompt = await run_llm_step(
        step_dir, step, alt, req, FakeClient(), "hello", 1,
        variables={"name": "Ada"},
    )
    assert output == "ok"
    # The role array reached the client with each content template rendered.
    assert captured["messages"] == [
        {"role": "system", "content": "You are Ada."},
        {"role": "user", "content": "Earlier: hello"},
        {"role": "user", "content": "Reply now."},
    ]
    # prompt.txt is the readable role-tagged concatenation.
    saved = (step_dir / "prompt.txt").read_text(encoding="utf-8")
    assert "[SYSTEM]\nYou are Ada." in saved
    assert "[USER]\nReply now." in saved
    assert prompt == saved


async def test_run_llm_step_messages_resolves_memory_token(tmp_path, monkeypatch):
    """A {{memory}} token inside a structured message is resolved from the step's
    retrieved memory block, landing in exactly the message that carries it."""
    from app.chain.models import (
        Alternative, ChainJobRequest, ChainLLMConfig, ChainStep, MemoryStepConfig,
    )
    from app.chain.steps import llm as llm_mod
    from app.chain.steps.llm import run_llm_step

    async def fake_block(*args, **kwargs):
        return "REMEMBERED FACTS"

    monkeypatch.setattr(llm_mod, "_retrieve_memory_block", fake_block)

    alt = Alternative(
        memory=MemoryStepConfig(enabled=True, query="q", scopes=[]),
        messages=[
            {"role": "system", "content": "Background:\n{{memory}}"},
            {"role": "user", "content": "Reply."},
        ],
    )
    step = ChainStep(name="turn", alternatives=[alt])
    req = ChainJobRequest(
        input="x",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[step],
    )

    captured: dict = {}

    class FakeClient:
        def chat_stream(self, messages, llm_config, tools=None):
            captured["messages"] = messages

            async def gen():
                yield StreamChunk(content="ok", finish_reason="stop")
            return gen()

    step_dir = tmp_path / "step"
    step_dir.mkdir()
    await run_llm_step(step_dir, step, alt, req, FakeClient(), "x", 1)
    contents = [m["content"] for m in captured["messages"]]
    assert "REMEMBERED FACTS" in contents[0]
    # Only the message with the token carries the block.
    assert "REMEMBERED FACTS" not in contents[1]
