"""SSE generators for chain job events.

Two flows:

- :func:`event_stream_from_bus` — subscribes to a live :class:`EventBus`,
  flushes history then forwards new events until ``job_done`` (or client
  disconnect). Heartbeats every 15s to keep proxies from idle-killing.
- :func:`event_stream_from_disk` — for jobs whose bus has been swept (or never
  existed), synthesize an equivalent event sequence from the on-disk artifacts
  in the job directory so the timeline UI has a single code path for both
  live and historical jobs.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import Request

from .events import ChainEvent, EventBus
from .executor import list_chain_steps

HEARTBEAT_INTERVAL_S = 15.0


def _format_sse(event: ChainEvent) -> str:
    body = json.dumps(event.to_json(), ensure_ascii=False)
    return f"event: {event.type}\ndata: {body}\n\n"


def _heartbeat_frame() -> str:
    return ": keepalive\n\n"


async def event_stream_from_bus(
    bus: EventBus, request: Request
) -> AsyncIterator[str]:
    """Yield SSE frames from a live bus until the job finishes or client leaves.

    Heartbeats every ``HEARTBEAT_INTERVAL_S`` keep proxies from idle-killing
    the connection. We run the heartbeat as a separate task that pushes into
    a single output queue, and the subscription loop pushes events into the
    same queue — so this generator is just a uniform consumer of that queue.
    """
    out: asyncio.Queue[Optional[str]] = asyncio.Queue()

    async def pump_events():
        try:
            async for evt in bus.subscribe():
                await out.put(_format_sse(evt))
                if evt.type == "job_done":
                    break
        finally:
            await out.put(None)  # sentinel: end of stream

    async def pump_heartbeats():
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_S)
                if await request.is_disconnected():
                    await out.put(None)
                    return
                await out.put(_heartbeat_frame())
        except asyncio.CancelledError:
            return

    events_task = asyncio.create_task(pump_events())
    heartbeat_task = asyncio.create_task(pump_heartbeats())
    try:
        while True:
            frame = await out.get()
            if frame is None:
                return
            yield frame
    finally:
        heartbeat_task.cancel()
        events_task.cancel()
        for t in (heartbeat_task, events_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_event(seq: int, type: str, **payload) -> ChainEvent:
    return ChainEvent(type=type, seq=seq, ts=_now_iso(), payload=payload)


async def event_stream_from_disk(
    job_id: str, job_dir: Path
) -> AsyncIterator[str]:
    """Reconstruct the event sequence from a finished job's disk state."""
    status_file = job_dir / "status.json"
    if not status_file.exists():
        return
    try:
        status = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    steps = list_chain_steps(job_dir)
    step_count = status.get("step_count") or len(steps)

    seq = 0
    def _next() -> int:
        nonlocal seq
        seq += 1
        return seq

    yield _format_sse(_make_event(_next(), "job_start", job_id=job_id, step_count=step_count))

    steps_dir = job_dir / "steps"

    for entry in steps:
        ptr = entry.get("step_number") or 0
        inv = entry.get("invocation") or 0
        step_type = entry.get("type") or ""
        step_id = entry.get("id") or ""
        name = entry.get("name") or ""

        yield _format_sse(_make_event(
            _next(), "step_start",
            step_number=ptr, invocation=inv, step_id=step_id,
            name=name, step_type=step_type, alt_index=0,
        ))

        # Locate the step's directory by reading the on-disk dir name.
        # _write_step_status doesn't record the dirname; reconstruct from the
        # naming convention.
        dir_name = f"{ptr:03d}_{step_id}" if inv == 0 else f"{ptr:03d}_{step_id}_x{inv:02d}"
        step_dir = steps_dir / dir_name

        # step_input — read prompt.txt for llm, fall back to nothing.
        prompt_text: Optional[str] = None
        if step_type == "llm":
            prompt_path = step_dir / "prompt.txt"
            if prompt_path.exists():
                try:
                    prompt_text = prompt_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            context_path = step_dir / "context.txt"
            context_text = None
            if context_path.exists():
                try:
                    context_text = context_path.read_text(encoding="utf-8") or None
                except OSError:
                    context_text = None
            if prompt_text is not None:
                yield _format_sse(_make_event(
                    _next(), "step_input",
                    step_number=ptr, invocation=inv,
                    rendered_prompt=prompt_text,
                    context=context_text,
                ))
        elif step_type in ("voice", "image_prompt", "save_wildcard", "create_ticket", "write_context"):
            # No reliable per-step "rendered_prompt" file for these on disk; we
            # use a placeholder so the timeline still creates an input node.
            yield _format_sse(_make_event(
                _next(), "step_input",
                step_number=ptr, invocation=inv,
                rendered_prompt="",
                context=None,
            ))

        # Type-specific body event.
        if step_type == "llm":
            # Reasoning trace (if the step ran with thinking on) — replayed
            # before the output so the Thinking block sits above it.
            reasoning_path = step_dir / "reasoning.txt"
            if reasoning_path.exists():
                try:
                    reasoning_text = reasoning_path.read_text(encoding="utf-8")
                except OSError:
                    reasoning_text = ""
                if reasoning_text:
                    yield _format_sse(_make_event(
                        _next(), "llm_reasoning",
                        step_number=ptr, invocation=inv, delta=reasoning_text,
                    ))
            output_path = step_dir / "output.txt"
            full_text = ""
            if output_path.exists():
                try:
                    full_text = output_path.read_text(encoding="utf-8")
                except OSError:
                    pass
            if full_text:
                # Replay the LLM response as one chunk so the timeline node
                # populates without needing a special "historical" branch.
                yield _format_sse(_make_event(
                    _next(), "llm_chunk",
                    step_number=ptr, invocation=inv, delta=full_text,
                ))
        elif step_type == "voice":
            for ext in ("wav", "mp3", "ogg"):
                output_path = step_dir / f"output.{ext}"
                if output_path.exists():
                    yield _format_sse(_make_event(
                        _next(), "artifact_ready",
                        step_number=ptr, invocation=inv,
                        kind="audio", filename=output_path.name,
                        file_url=f"/v1/jobs/{job_id}/files/steps/{dir_name}/{output_path.name}",
                        mime=f"audio/{ext}",
                    ))
                    break
        elif step_type in ("write_context", "image_prompt", "save_wildcard", "create_ticket"):
            output_path = step_dir / "output.json"
            if output_path.exists():
                try:
                    data = json.loads(output_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
                summary = _summary_for(step_type, data)
                yield _format_sse(_make_event(
                    _next(), "summary",
                    step_number=ptr, invocation=inv,
                    kind=step_type, summary=summary, detail=data,
                ))

        # step_done — pull status / error / full_text from the entry.
        if entry.get("status") == "error":
            yield _format_sse(_make_event(
                _next(), "step_error",
                step_number=ptr, invocation=inv,
                error=entry.get("error") or "unknown error",
            ))
        else:
            full_text = None
            if step_type == "llm":
                output_path = step_dir / "output.txt"
                if output_path.exists():
                    try:
                        full_text = output_path.read_text(encoding="utf-8")
                    except OSError:
                        full_text = None
            output_rel = entry.get("output_file")
            output_rel_full = f"steps/{dir_name}/{output_rel}" if output_rel else None
            yield _format_sse(_make_event(
                _next(), "step_done",
                step_number=ptr, invocation=inv,
                status=entry.get("status") or "done",
                output_file=output_rel_full,
                full_text=full_text,
            ))

    # job_done — synthesize from final status.
    final_output = None
    final_path = job_dir / "final_output.txt"
    if final_path.exists():
        try:
            final_output = final_path.read_text(encoding="utf-8")
        except OSError:
            final_output = None
    artifacts_path = job_dir / "artifacts.json"
    artifacts = []
    if artifacts_path.exists():
        try:
            artifacts = json.loads(artifacts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            artifacts = []
    yield _format_sse(_make_event(
        _next(), "job_done",
        status=status.get("status") or "done",
        error=status.get("error"),
        final_output=final_output,
        artifacts=artifacts,
        duration_ms=None,
    ))


def _summary_for(step_type: str, data: dict) -> str:
    if step_type == "write_context":
        title = data.get("title") or ""
        return f"Saved to context: {title}" if title else "Wrote context item"
    if step_type == "image_prompt":
        name = data.get("name") or ""
        return f"Saved image prompt: {name}" if name else "Saved image prompt"
    if step_type == "save_wildcard":
        action = data.get("action") or "save"
        wc = data.get("wildcard") or {}
        name = wc.get("name") or ""
        return f"Wildcard {action}: {name}" if name else f"Wildcard {action}"
    if step_type == "create_ticket":
        title = data.get("title") or ""
        return f"Created ticket: {title}" if title else "Created ticket"
    return step_type
