from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_chat_stream_mock(outputs):
    from app.chain.llm_client import StreamChunk

    iterator = iter(outputs)

    def factory(*args, **kwargs):
        nxt = next(iterator)

        async def gen():
            if isinstance(nxt, Exception):
                raise nxt
            yield StreamChunk(content=nxt, finish_reason="stop")

        return gen()

    return MagicMock(side_effect=factory)


async def test_event_stream_from_bus_replays_history_then_live():
    from app.chain.events import EventBus
    from app.chain.sse import event_stream_from_bus

    bus = EventBus("job-live")
    bus.emit("job_start", job_id="job-live", step_count=1)

    class FakeRequest:
        async def is_disconnected(self):
            return False

    frames: list[str] = []

    async def consumer():
        async for frame in event_stream_from_bus(bus, FakeRequest()):
            frames.append(frame)

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    bus.emit("step_start", step_number=1, invocation=0, step_id="x",
             name="x", step_type="llm", alt_index=0)
    bus.emit("llm_chunk", step_number=1, invocation=0, delta="hello")
    bus.emit("step_done", step_number=1, invocation=0, status="done",
             output_file="steps/001_x/output.txt", full_text="hello")
    bus.emit("job_done", status="done", final_output="hello", artifacts=[],
             duration_ms=42)
    await asyncio.wait_for(task, timeout=2.0)

    types_seen = [f.split("\n")[0].removeprefix("event: ") for f in frames]
    assert "job_start" in types_seen
    assert "llm_chunk" in types_seen
    assert types_seen[-1] == "job_done"
    # SSE framing — each frame ends with blank line.
    for f in frames:
        assert f.endswith("\n\n")


async def test_event_stream_from_disk_synthesizes_completed_job(tmp_path):
    """Drive a chain job to completion with the LLM mocked, then verify the
    disk-snapshot path produces the expected event sequence."""
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.chain.sse import event_stream_from_disk
    from app.jobs import create_job, find_job_dir

    req = ChainJobRequest(
        input="hi",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[ChainStep(name="hello step", prompt="Say: {{input}}")],
    )
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_stream = _make_chat_stream_mock(["hello world"])
        await execute_chain_job(job_id, job_dir, req)

    frames: list[str] = []
    async for f in event_stream_from_disk(job_id, job_dir):
        frames.append(f)

    types_seen = [f.split("\n")[0].removeprefix("event: ") for f in frames]
    assert types_seen[0] == "job_start"
    assert "step_start" in types_seen
    assert "step_input" in types_seen
    assert "llm_chunk" in types_seen   # synthesized one-shot from output.txt
    assert "step_done" in types_seen
    assert types_seen[-1] == "job_done"

    # The llm_chunk frame should carry the full output text as a single delta.
    llm_chunk_frame = next(f for f in frames if f.startswith("event: llm_chunk"))
    body = llm_chunk_frame.split("data: ", 1)[1].rstrip()
    payload = json.loads(body)
    assert payload["delta"] == "hello world"
    assert payload["step_number"] == 1


async def test_reasoning_persisted_and_replayed_before_output(tmp_path):
    """A step run with thinking on writes reasoning.txt; the disk-replay path
    emits an llm_reasoning frame (the Thinking block) before the llm_chunk."""
    from app.chain.executor import execute_chain_job
    from app.chain.llm_client import StreamChunk
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.chain.sse import event_stream_from_disk
    from app.jobs import create_job, find_job_dir

    req = ChainJobRequest(
        input="hi",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[ChainStep(name="think step", prompt="Say: {{input}}", thinking=True)],
    )
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    def factory(*args, **kwargs):
        async def gen():
            yield StreamChunk(reasoning="weighing options")
            yield StreamChunk(content="final answer", finish_reason="stop")
        return gen()

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        MockClient.return_value.chat_stream = MagicMock(side_effect=factory)
        await execute_chain_job(job_id, job_dir, req)

    # reasoning persisted next to output, output itself clean.
    step_dir = next((job_dir / "steps").iterdir())
    assert (step_dir / "reasoning.txt").read_text() == "weighing options"
    assert (step_dir / "output.txt").read_text() == "final answer"

    frames = [f async for f in event_stream_from_disk(job_id, job_dir)]
    types_seen = [f.split("\n")[0].removeprefix("event: ") for f in frames]
    assert "llm_reasoning" in types_seen
    # Thinking block comes before the answer.
    assert types_seen.index("llm_reasoning") < types_seen.index("llm_chunk")
    reasoning_frame = next(f for f in frames if f.startswith("event: llm_reasoning"))
    payload = json.loads(reasoning_frame.split("data: ", 1)[1].rstrip())
    assert payload["delta"] == "weighing options"


async def test_executor_emits_lifecycle_events_to_bus(tmp_path):
    from app.chain.events import EventBus
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.jobs import create_job, find_job_dir

    req = ChainJobRequest(
        input="hi",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[
            ChainStep(name="one", prompt="A: {{input}}"),
            ChainStep(name="two", prompt="B: {{previous}}"),
        ],
    )
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)
    bus = EventBus(job_id)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_stream = _make_chat_stream_mock(["one_out", "two_out"])
        await execute_chain_job(job_id, job_dir, req, event_bus=bus)

    types_seen = [e.type for e in bus.history()]
    # job_start, then per-step: step_start, step_input, step_done; then job_done.
    assert types_seen[0] == "job_start"
    assert types_seen.count("step_start") == 2
    assert types_seen.count("step_input") == 2
    assert types_seen.count("step_done") == 2
    assert types_seen[-1] == "job_done"

    # seq is monotonic
    seqs = [e.seq for e in bus.history()]
    assert seqs == sorted(seqs)
    assert seqs[0] == 1


async def test_executor_emits_step_error_and_job_done_error_on_failure(tmp_path):
    from app.chain.events import EventBus
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.jobs import create_job, find_job_dir

    req = ChainJobRequest(
        input="start",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[ChainStep(name="boom", prompt="{{input}}")],
    )
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)
    bus = EventBus(job_id)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.chat_stream = _make_chat_stream_mock([RuntimeError("nope")])
        await execute_chain_job(job_id, job_dir, req, event_bus=bus)

    types_seen = [e.type for e in bus.history()]
    assert "step_error" in types_seen
    final = bus.history()[-1]
    assert final.type == "job_done"
    assert final.payload["status"] == "error"
    assert "nope" in final.payload.get("error", "")


def test_sse_endpoint_404_for_missing_job(client):
    r = client.get("/v1/jobs/does-not-exist/stream")
    assert r.status_code == 404
