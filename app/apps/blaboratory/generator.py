"""Resident generation: a 2-step LLM chain, run synchronously.

Per design.md §"Generation flow" this drives the existing chain executor
**directly** (not via the shared `JobQueue`, so background generation never
starves real jobs), within the request:

1. `create_job("blaboratory_resident", …)` scaffolds an on-disk job (visible in
   the Jobs page for debuggability).
2. A 2-step `ChainJobRequest` — **ideate** (free-text or guided prose) then
   **assemble** (strict JSON). LLM config comes from
   `get_default_as_chain_llm_config()`.
3. `await execute_chain_job(...)` runs it; `final_output.txt` holds the JSON.
4. Parse (fence-strip → `json.loads` → `ResidentDraft`), retrying assemble-only
   (≤2) seeded with the captured ideate prose on parse failure.
5. Merge with user-supplied guided fields (user wins), build a full `Resident`.
6. Persist **resident first, then occupancy**, so a crash never points
   occupancy at a missing resident.

On unrecoverable failure the job is marked `error` and `GenerationError` is
raised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ...chain.executor import execute_chain_job
from ...chain.models import Alternative, ChainJobRequest, ChainLLMConfig, ChainStep
from ...jobs import _write_status, create_job, find_job_dir
from ...llm_config import get_default_as_chain_llm_config
from . import residents_store, rooms
from .models import ResidentDraft
from .prompts import get_prompt

JOB_TYPE = "blaboratory_resident"
MAX_PARSE_RETRIES = 2


class GenerationError(Exception):
    """Raised when resident generation cannot produce a valid resident."""


def _format_guided_fields(fields: dict) -> str:
    """Render user-supplied guided fields as a readable list for the prompt."""
    lines: list[str] = []
    for key, value in fields.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = json.dumps(value)
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "(no fields specified)"


def _llm_step(number: int, step_id: str, name: str, prompt: str) -> ChainStep:
    return ChainStep(
        number=number,
        id=step_id,
        name=name,
        type="llm",
        alternatives=[Alternative(prompt=prompt)],
    )


def build_generation_request(
    mode: str,
    free_text: Optional[str],
    fields: Optional[dict],
    llm: ChainLLMConfig,
) -> ChainJobRequest:
    """Build the 2-step ideate→assemble chain for the given mode."""
    if mode == "free_text":
        ideate_prompt = get_prompt("IDEATE_FREE_TEXT")
        seed_input = (free_text or "").strip()
    elif mode == "guided":
        ideate_prompt = get_prompt("IDEATE_GUIDED")
        seed_input = _format_guided_fields(fields or {})
    else:
        raise ValueError(f"unknown mode: {mode!r} (expected 'free_text' or 'guided')")

    return ChainJobRequest(
        title="Blaboratory resident",
        input=seed_input,
        llm=llm,
        steps=[
            _llm_step(1, "ideate", "Ideate", ideate_prompt),
            _llm_step(2, "assemble", "Assemble", get_prompt("ASSEMBLE")),
        ],
    )


def _build_assemble_only_request(prose: str, llm: ChainLLMConfig) -> ChainJobRequest:
    """Single assemble step seeded with captured ideate prose (retry path).

    The assemble prompt reads `{{previous}}`, which for a single-step chain is
    the request's `input`, so the prose flows through unchanged.
    """
    return ChainJobRequest(
        title="Blaboratory resident (retry)",
        input=prose,
        llm=llm,
        steps=[_llm_step(1, "assemble", "Assemble", get_prompt("ASSEMBLE"))],
    )


def _strip_fences(text: str) -> str:
    """Strip a leading/trailing ``` or ```json fence if present."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def parse_resident_json(text: str) -> ResidentDraft:
    """Fence-strip, `json.loads`, validate into `ResidentDraft`.

    Raises `json.JSONDecodeError` on malformed JSON or `pydantic.ValidationError`
    on a shape mismatch.
    """
    data = json.loads(_strip_fences(text))
    return ResidentDraft(**data)


def _read_final_output(job_dir: Path) -> str:
    p = job_dir / "final_output.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _read_ideate_prose(job_dir: Path) -> str:
    """Best-effort read of the ideate step's prose output for the retry seed."""
    for p in sorted((job_dir / "steps").glob("*_ideate/output.txt")):
        return p.read_text(encoding="utf-8")
    return ""


async def run_generation(
    room_id: int,
    mode: str,
    free_text: Optional[str] = None,
    fields: Optional[dict] = None,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[dict, str]:
    """Generate a resident and place it in `room_id`.

    Returns `(resident, job_id)`. Raises `GenerationError` if the room is
    occupied or generation fails after retries; the job is marked `error` in
    the latter case.
    """
    if not rooms.is_empty(room_id):
        raise GenerationError(f"room {room_id} is already occupied")

    if llm is None:
        try:
            llm = get_default_as_chain_llm_config()
        except RuntimeError as exc:
            # e.g. no default endpoint preset configured — report cleanly, not 500.
            raise GenerationError(str(exc)) from exc
    # Resident generation wants prose/JSON, not a reasoning trace. Reasoning
    # models (e.g. the supergemma thinking build) otherwise spend the whole
    # token budget thinking and stream back empty content; this disables it.
    if llm.chat_template_kwargs is None:
        llm = llm.model_copy(update={"chat_template_kwargs": {"enable_thinking": False}})
    request = build_generation_request(mode, free_text, fields, llm)

    status = create_job(JOB_TYPE, request.model_dump(), request.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover - create_job just made it
        raise GenerationError("job directory disappeared after creation")

    await execute_chain_job(job_id, job_dir, request)

    draft: Optional[ResidentDraft] = None
    last_error: Optional[Exception] = None
    try:
        draft = parse_resident_json(_read_final_output(job_dir))
    except Exception as exc:  # noqa: BLE001 - parse/validation failure → retry
        last_error = exc
        prose = _read_ideate_prose(job_dir) or _read_final_output(job_dir)
        for _ in range(MAX_PARSE_RETRIES):
            await execute_chain_job(job_id, job_dir, _build_assemble_only_request(prose, llm))
            try:
                draft = parse_resident_json(_read_final_output(job_dir))
                last_error = None
                break
            except Exception as retry_exc:  # noqa: BLE001
                last_error = retry_exc

    if draft is None:
        _write_status(job_dir, "error", error=f"resident generation failed: {last_error}")
        raise GenerationError(f"generation failed after retries: {last_error}")

    merged = draft.model_dump(exclude_none=True)
    if mode == "guided" and fields:
        for key, value in fields.items():
            if value not in (None, "", [], {}):
                merged[key] = value

    try:
        resident = residents_store.create_resident(merged)
    except Exception as exc:  # noqa: BLE001 - merged doc still incomplete/invalid
        _write_status(job_dir, "error", error=f"resident assembly failed: {exc}")
        raise GenerationError(f"could not build resident: {exc}") from exc

    try:
        rooms.set_occupant(room_id, resident["id"])
    except ValueError as exc:
        _write_status(job_dir, "error", error=f"occupancy failed: {exc}")
        raise GenerationError(str(exc)) from exc

    return resident, job_id
