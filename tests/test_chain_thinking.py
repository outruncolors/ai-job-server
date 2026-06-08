"""Per-step reasoning ('thinking') control.

Thinking is the project default (DEFAULT_THINKING); only steps that explicitly
set ``thinking=False`` suppress it. The flag is realized as a per-request
``thinking_budget_tokens`` (0 = off, -1 = on) on the chat-completions body — no
model reload involved.
"""

from __future__ import annotations

import json

import httpx

from app.chain.models import (
    DEFAULT_THINKING,
    Alternative,
    ChainLLMConfig,
    ChainStep,
)
from app.chain.llm_client import OpenAICompatibleLLMClient, StreamChunk
from app.chain.steps.llm import _strip_think_block, _stream_assistant_turn


# ---- model: field + v1 hoist -----------------------------------------------

def test_alternative_thinking_defaults_to_none():
    assert Alternative(prompt="hi").thinking is None


def test_thinking_round_trips():
    assert Alternative(prompt="hi", thinking=False).thinking is False
    assert Alternative(prompt="hi", thinking=True).thinking is True


def test_flat_v1_step_hoists_thinking_into_alternative():
    step = ChainStep(name="s", type="llm", prompt="hi", thinking=False)
    assert step.primary.thinking is False


# ---- budget resolution (the executor's rule) -------------------------------

def _budget_for(alt: Alternative) -> int:
    thinking = alt.thinking if alt.thinking is not None else DEFAULT_THINKING
    return -1 if thinking else 0


def test_budget_off_when_thinking_false():
    assert _budget_for(Alternative(prompt="x", thinking=False)) == 0


def test_budget_on_when_thinking_true():
    assert _budget_for(Alternative(prompt="x", thinking=True)) == -1


def test_budget_default_tracks_project_default():
    # An unset (None) thinking flag follows DEFAULT_THINKING, whichever way it points.
    assert _budget_for(Alternative(prompt="x")) == (-1 if DEFAULT_THINKING else 0)


# ---- client puts thinking_budget_tokens on the wire ------------------------

def _capture_transport(captured: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch, captured: dict) -> None:
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = _capture_transport(captured)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


async def test_generate_sends_thinking_budget_at_top_level(monkeypatch):
    captured: dict = {}
    _patch_client(monkeypatch, captured)
    cfg = ChainLLMConfig(api_base="http://fake", model="m", thinking_budget_tokens=0)
    out = await OpenAICompatibleLLMClient().generate("hi", cfg)
    assert out == "ok"
    # Top-level field, NOT nested inside chat_template_kwargs.
    assert captured["body"]["thinking_budget_tokens"] == 0
    assert "chat_template_kwargs" not in captured["body"]


async def test_generate_omits_budget_when_unset(monkeypatch):
    captured: dict = {}
    _patch_client(monkeypatch, captured)
    cfg = ChainLLMConfig(api_base="http://fake", model="m")  # thinking_budget_tokens None
    await OpenAICompatibleLLMClient().generate("hi", cfg)
    assert "thinking_budget_tokens" not in captured["body"]


# ---- defensive <think> strip -----------------------------------------------

def test_strip_think_block_removes_leading_reasoning():
    assert _strip_think_block("<think>plan</think>Answer") == "Answer"
    assert _strip_think_block("  <think>\nmulti\nline\n</think>\n\nFinal") == "Final"


def test_strip_think_block_leaves_clean_output_untouched():
    assert _strip_think_block("Just an answer") == "Just an answer"


# ---- reasoning channel: stream capture + event emission --------------------

async def test_chat_stream_captures_reasoning_content(monkeypatch):
    import json as _json

    body = (
        "data: " + _json.dumps({"choices": [{"delta": {"reasoning_content": "let me think"}}]}) + "\n\n"
        "data: " + _json.dumps({"choices": [{"delta": {"content": "answer"}, "finish_reason": "stop"}]}) + "\n\n"
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    cfg = ChainLLMConfig(api_base="http://fake", model="m")
    chunks = []
    async for c in OpenAICompatibleLLMClient().chat_stream([{"role": "user", "content": "hi"}], cfg):
        chunks.append(c)
    assert "".join(c.reasoning for c in chunks) == "let me think"
    assert "".join(c.content for c in chunks) == "answer"


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks

    async def chat_stream(self, messages, llm_config, tools=None):
        for c in self._chunks:
            yield c


class _FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, event_type, **payload):
        self.events.append((event_type, payload))


async def test_stream_assistant_turn_emits_reasoning_and_returns_both():
    client = _FakeClient([
        StreamChunk(reasoning="think A"),
        StreamChunk(reasoning="think B"),
        StreamChunk(content="hello", finish_reason="stop"),
    ])
    bus = _FakeBus()
    output, reasoning = await _stream_assistant_turn(
        [{"role": "user", "content": "hi"}], client, None, bus, 1, 0
    )
    assert output == "hello"
    assert reasoning == "think Athink B"
    types = [t for t, _ in bus.events]
    # Reasoning emitted before the content chunk, on its own channel.
    assert types == ["llm_reasoning", "llm_reasoning", "llm_chunk"]


async def test_stream_assistant_turn_no_reasoning_when_thinking_off():
    client = _FakeClient([StreamChunk(content="hi", finish_reason="stop")])
    bus = _FakeBus()
    output, reasoning = await _stream_assistant_turn(
        [{"role": "user", "content": "x"}], client, None, bus, 1, 0
    )
    assert output == "hi"
    assert reasoning == ""
    assert [t for t, _ in bus.events] == ["llm_chunk"]
