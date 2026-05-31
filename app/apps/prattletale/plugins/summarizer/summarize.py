"""Hierarchical map-reduce summarization over the chain executor.

``summarize_history`` reduces a conversation transcript to a single summary string:

1. **Collect** the covered turns — every turn with an item currently visible in
   context (not ``hidden_from_context``, not ``system_error``). A prior ``summary``
   turn is visible, so re-summarizing naturally folds it in; already-purged
   originals are excluded.
2. **Chunk** the covered turns into slices of ``chunk_turns``.
3. **Map** — summarize each chunk via the ``summarize.map`` Prompt Pal entry.
4. **Reduce** — while more than one partial remains, group them (fan-in
   ``reduce_fanin``) and merge each group via ``summarize.reduce``; a singleton
   group passes through unchanged. Repeat until one summary remains.

Each LLM call is one direct ``execute_chain_job`` (foreground, like a turn) — long
histories mean more calls, acceptable for a manual on-demand action. A
single-chunk history skips the reduce stage. The chosen detail level is composed
from the matching ``summarize.level.<level>`` entry into ``{{var.detail}}``, and
``focus`` is appended at the end of each prompt.

``execute_chain_job`` / ``create_job`` / ``find_job_dir`` / ``get_text`` are
referenced as module-level names so tests can stub the executor.
"""

from __future__ import annotations

from typing import Optional

from app.apps.prattletale.generator import (
    GenerationError,
    _flatten_transcript,
    _llm_step,
    _read_final_output,
    _resolve_llm,
)
from app.apps.prattletale.models import ItemType
from app.chain.executor import execute_chain_job
from app.chain.models import ChainJobRequest, ChainLLMConfig
from app.jobs import create_job, find_job_dir
from app.prompt_pal.service import get_text

from . import prompts  # noqa: F401 — ensure summarize.* Prompt Pal entries are registered

JOB_TYPE = "prattletale_summarize"

VALID_LEVELS = ("brief", "standard", "detailed")


def _covered_turns(transcript: dict) -> list[dict]:
    """Turns with at least one item visible in context (skip hidden / error items)."""
    covered: list[dict] = []
    for turn in transcript.get("turns") or []:
        visible = [
            it for it in (turn.get("items") or [])
            if not it.get("hidden_from_context")
            and it.get("type") != ItemType.system_error.value
        ]
        if visible:
            covered.append(turn)
    return covered


def _chunk(items: list, size: int) -> list[list]:
    size = max(1, int(size))
    return [items[i:i + size] for i in range(0, len(items), size)]


def _focus_directive(focus: str) -> str:
    """Render the optional focus note as a trailing directive (empty when blank)."""
    focus = (focus or "").strip()
    return f"Focus especially on, and emphasize: {focus}" if focus else ""


async def _run_summary_job(title: str, prompt: str, llm: ChainLLMConfig) -> str:
    """Run a single-step LLM chain job and return its ``final_output.txt``.

    Mirrors :func:`generator.run_model_turn`'s scaffolding (a real on-disk job for
    debuggability), but is a clean one-shot — no parsing, no persistence."""
    request = ChainJobRequest(
        title=title,
        input=prompt,
        llm=llm,
        steps=[_llm_step(1, "summarize", "Summarize", prompt)],
    )
    status = create_job(JOB_TYPE, request.model_dump(), request.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover — create_job just made it
        raise GenerationError("job directory disappeared after creation")
    await execute_chain_job(job_id, job_dir, request)
    return _read_final_output(job_dir).strip()


async def summarize_history(
    conversation: dict,
    character: dict,
    transcript: dict,
    *,
    level: str,
    focus: str = "",
    chunk_turns: int = 6,
    reduce_fanin: int = 4,
    llm: Optional[ChainLLMConfig] = None,
) -> str:
    """Reduce the conversation's covered history to a single summary string.

    ``level`` is one of :data:`VALID_LEVELS`. Returns ``""`` when there is nothing
    visible to summarize (the caller decides whether that's an error)."""
    if level not in VALID_LEVELS:
        raise ValueError(f"unknown detail level: {level!r}")

    resolved = _resolve_llm(llm)
    detail = get_text("prattletale", f"summarize.level.{level}").strip()
    focus_directive = _focus_directive(focus)

    turns = _covered_turns(transcript)
    if not turns:
        return ""

    # Map: one partial summary per chunk of turns.
    partials: list[str] = []
    for chunk in _chunk(turns, chunk_turns):
        chunk_text = _flatten_transcript(chunk, character)
        prompt = get_text(
            "prattletale", "summarize.map",
            variables={"detail": detail, "transcript": chunk_text, "focus": focus_directive},
        )
        partials.append(await _run_summary_job("Summarize chunk", prompt, resolved))

    # Reduce: hierarchically merge until a single summary remains. A singleton
    # group passes through unchanged (no wasted LLM call).
    while len(partials) > 1:
        merged: list[str] = []
        for group in _chunk(partials, reduce_fanin):
            if len(group) == 1:
                merged.append(group[0])
                continue
            joined = "\n\n".join(f"- {p}" for p in group)
            prompt = get_text(
                "prattletale", "summarize.reduce",
                variables={"detail": detail, "partials": joined, "focus": focus_directive},
            )
            merged.append(await _run_summary_job("Reduce summaries", prompt, resolved))
        partials = merged

    return partials[0].strip()
