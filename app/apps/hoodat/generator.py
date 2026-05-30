"""Character generation for Hoodat — chain jobs run synchronously.

Mirrors `app/apps/blaboratory/generator.py`: drives the chain executor
**directly** (not via the shared `JobQueue`, so background generation never
starves real jobs), scaffolding an on-disk job for debuggability.

- `run_create(name, prompt)` — 2-step ideate→assemble, parse with ≤2 retries,
  merge the user's name, persist a `Character`.
- `run_field(character_id, section, field)` — single-step generate one field
  from the rest of the character, normalize per the field's kind, persist.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ...chain.executor import execute_chain_job
from ...chain.models import Alternative, ChainJobRequest, ChainLLMConfig, ChainStep
from ...jobs import _write_status, create_job, find_job_dir
from ...llm_config import get_default_as_chain_llm_config
from ...prompt_pal.service import get_text, id_for
from . import characters_store
from .models import CharacterDraft, field_spec
from .prompts import render_character_context

CREATE_JOB_TYPE = "hoodat_character"
FIELD_JOB_TYPE = "hoodat_field"
MAX_PARSE_RETRIES = 2


class GenerationError(Exception):
    """Raised when generation cannot produce a valid result."""


# ---- shared helpers --------------------------------------------------------

def _resolve_llm(llm: Optional[ChainLLMConfig]) -> ChainLLMConfig:
    if llm is None:
        try:
            llm = get_default_as_chain_llm_config()
        except RuntimeError as exc:
            raise GenerationError(str(exc)) from exc
    # Want prose/JSON, not a reasoning trace (same rationale as Blaboratory).
    if llm.chat_template_kwargs is None:
        llm = llm.model_copy(update={"chat_template_kwargs": {"enable_thinking": False}})
    return llm


def _llm_step(number: int, step_id: str, name: str, prompt: str) -> ChainStep:
    return ChainStep(
        number=number, id=step_id, name=name, type="llm",
        alternatives=[Alternative(prompt=prompt)],
    )


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _read_final_output(job_dir: Path) -> str:
    p = job_dir / "final_output.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _read_ideate_prose(job_dir: Path) -> str:
    for p in sorted((job_dir / "steps").glob("*_ideate/output.txt")):
        return p.read_text(encoding="utf-8")
    return ""


# ---- create-from-prompt ----------------------------------------------------

def parse_character_json(text: str) -> CharacterDraft:
    data = json.loads(_strip_fences(text))
    return CharacterDraft(**data)


def build_generation_request(name: str, prompt: str, llm: ChainLLMConfig) -> ChainJobRequest:
    seed = f"Name: {name.strip()}\nDescription: {(prompt or '').strip()}"
    return ChainJobRequest(
        title="Hoodat character",
        input=seed,
        llm=llm,
        steps=[
            _llm_step(1, "ideate", "Ideate", get_text("hoodat", "IDEATE")),
            _llm_step(2, "assemble", "Assemble", get_text("hoodat", "ASSEMBLE")),
        ],
    )


def _build_assemble_only_request(prose: str, llm: ChainLLMConfig) -> ChainJobRequest:
    return ChainJobRequest(
        title="Hoodat character (retry)",
        input=prose,
        llm=llm,
        steps=[_llm_step(1, "assemble", "Assemble", get_text("hoodat", "ASSEMBLE"))],
    )


async def run_create(name: str, prompt: str, llm: Optional[ChainLLMConfig] = None) -> tuple[dict, str]:
    """Generate a character from `name` + `prompt`. Returns `(character, job_id)`."""
    if not (name or "").strip():
        raise GenerationError("name is required")
    llm = _resolve_llm(llm)
    request = build_generation_request(name, prompt, llm)

    status = create_job(CREATE_JOB_TYPE, request.model_dump(), request.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        raise GenerationError("job directory disappeared after creation")

    await execute_chain_job(job_id, job_dir, request)

    draft: Optional[CharacterDraft] = None
    last_error: Optional[Exception] = None
    try:
        draft = parse_character_json(_read_final_output(job_dir))
    except Exception as exc:  # noqa: BLE001 — parse/validation failure → retry
        last_error = exc
        prose = _read_ideate_prose(job_dir) or _read_final_output(job_dir)
        for _ in range(MAX_PARSE_RETRIES):
            await execute_chain_job(job_id, job_dir, _build_assemble_only_request(prose, llm))
            try:
                draft = parse_character_json(_read_final_output(job_dir))
                last_error = None
                break
            except Exception as retry_exc:  # noqa: BLE001
                last_error = retry_exc

    if draft is None:
        _write_status(job_dir, "error", error=f"character generation failed: {last_error}")
        raise GenerationError(f"generation failed after retries: {last_error}")

    merged = draft.model_dump(exclude_none=True)
    merged["name"] = name.strip()  # user-supplied name always wins

    try:
        character = characters_store.create_character(merged)
    except Exception as exc:  # noqa: BLE001
        _write_status(job_dir, "error", error=f"character assembly failed: {exc}")
        raise GenerationError(f"could not build character: {exc}") from exc

    return character, job_id


# ---- per-field generation --------------------------------------------------

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _normalize_value(raw: str, kind: str):
    text = _strip_fences(raw).strip()
    if kind == "list":
        items = []
        for line in text.splitlines():
            cleaned = _BULLET_RE.sub("", line).strip().strip('"')
            if cleaned:
                items.append(cleaned)
        # tolerate a comma-separated single line
        if len(items) <= 1 and "," in text:
            items = [s.strip().strip('"') for s in text.split(",") if s.strip()]
        return items
    if kind == "int":
        m = re.search(r"-?\d+", text)
        if m is None:
            raise GenerationError(f"expected a number, got: {text!r}")
        return int(m.group(0))
    # scalar: collapse to a single trimmed line
    return text.splitlines()[0].strip().strip('"') if text else ""


def _patch_for(section: str, field: str, value) -> dict:
    if section == "identity":
        return {field: value}
    return {section: {field: value}}


async def run_field(
    character_id: str,
    section: str,
    field: str,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[object, Optional[str], str]:
    """Generate one field from the rest of the character. Returns
    `(value, prompt_id, job_id)`. `prompt_id` is the Prompt Pal entry id (for
    the field's Edit-prompt link), or None if not seeded.
    """
    spec = field_spec(section, field)
    if spec is None:
        raise GenerationError(f"unknown field: {section}.{field}")
    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    key = f"field.{section}.{field}"
    rendered_context = render_character_context(character)
    prompt = get_text("hoodat", key, variables={"character": rendered_context})

    request = ChainJobRequest(
        title=f"Hoodat field {section}.{field}",
        input=rendered_context,
        llm=llm,
        steps=[_llm_step(1, "field", f"Field {field}", prompt)],
    )
    status = create_job(FIELD_JOB_TYPE, request.model_dump(), request.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        raise GenerationError("job directory disappeared after creation")

    await execute_chain_job(job_id, job_dir, request)

    try:
        value = _normalize_value(_read_final_output(job_dir), spec["kind"])
    except GenerationError:
        _write_status(job_dir, "error", error="field value could not be parsed")
        raise

    updated = characters_store.update_character_fields(
        character_id, _patch_for(section, field, value)
    )
    if updated is None:  # pragma: no cover — checked above
        raise GenerationError(f"character disappeared: {character_id}")

    return value, id_for("hoodat", key), job_id
