"""Character generation for Hoodat — chain jobs run synchronously.

Mirrors `app/apps/blaboratory/generator.py`: drives the chain executor
**directly** (not via the shared `JobQueue`, so background generation never
starves real jobs), scaffolding an on-disk job for debuggability.

- `run_create(name, prompt)` — 2-step ideate→assemble, parse with ≤2 retries,
  merge the user's name, persist a `Character`.
- `run_field(character_id, section, field)` — single-step generate one field
  from the rest of the character, normalize per the field's kind, persist.
- `run_dialogue_example(character_id, examples)` — single-step generate one new
  dialogue example from the character + prior examples (no persistence; the
  frontend owns the list).
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
from ...prompt_pal.service import get_guard, get_text, id_for
from . import characters_store
from .models import OUTFIT_SLOTS, CharacterDraft, field_spec
from .prompts import render_character_context

CREATE_JOB_TYPE = "hoodat_character"
FIELD_JOB_TYPE = "hoodat_field"
DIALOGUE_JOB_TYPE = "hoodat_dialogue"
EXPERIENCE_JOB_TYPE = "hoodat_experience"
OUTFIT_JOB_TYPE = "hoodat_outfit"
QA_JOB_TYPE = "hoodat_qa"
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


# ---- dialogue examples -----------------------------------------------------

def _normalize_dialogue(raw: str) -> str:
    """Clean a generated dialogue example. Unlike `_normalize_value(scalar)`,
    keep internal newlines (a short exchange may span lines)."""
    t = _strip_fences(raw).strip()
    # strip a single wrapping quote pair if the whole thing is quoted
    if len(t) >= 2 and t[0] in "\"'" and t[-1] == t[0]:
        t = t[1:-1].strip()
    return t


async def run_dialogue_example(
    character_id: str,
    examples: Optional[list[str]] = None,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[str, Optional[str], str]:
    """Generate one new dialogue example from the character + prior `examples`.

    Returns `(value, prompt_id, job_id)`. Does **not** persist — the frontend
    owns the list and writes the full edited list back via `PUT /characters/{id}`
    (the list is replaced wholesale by the nested-section merge).
    """
    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    key = "dialogue.example"
    rendered_context = render_character_context(character)
    examples_text = "\n".join(f"- {e}" for e in (examples or [])) or "(none yet)"
    prompt = get_text("hoodat", key, variables={
        "character": rendered_context, "examples": examples_text,
    })

    job_dir = await _run_single_step(
        DIALOGUE_JOB_TYPE, "Hoodat dialogue example", "dialogue", prompt, rendered_context, llm,
        guard_prompt=get_guard("hoodat", key),
    )
    value = _normalize_dialogue(_read_final_output(job_dir))
    return value, id_for("hoodat", key), _job_id_from_dir(job_dir)


# ---- Q&A (AliChat interview exemplars) -------------------------------------

def _qa_text(pairs: Optional[list[dict]]) -> str:
    """Render prior Q&A pairs as few-shot context for `{{var.qa}}`."""
    items = [
        p for p in (pairs or [])
        if str(p.get("question") or "").strip() and str(p.get("answer") or "").strip()
    ]
    if not items:
        return "(none yet)"
    return "\n".join(
        f"Q: {str(p['question']).strip()}\nA: {str(p['answer']).strip()}" for p in items
    )


async def run_qa_answer(
    character_id: str,
    question: str,
    pairs: Optional[list[dict]] = None,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[str, Optional[str], str]:
    """Answer an interview `question` in the character's voice, using prior
    `pairs` as few-shot context. The `qa.answer` prompt carries a spoken-only
    guard, so the returned answer is TTS-safe (no actions/symbols).

    Returns `(answer, prompt_id, job_id)`. Does **not** persist — the frontend
    owns the Q&A list and PUTs it wholesale.
    """
    if not (question or "").strip():
        raise GenerationError("question is required")
    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    key = "qa.answer"
    rendered_context = render_character_context(character)
    prompt = get_text("hoodat", key, variables={
        "character": rendered_context, "question": question.strip(), "qa": _qa_text(pairs),
    })
    job_dir = await _run_single_step(
        QA_JOB_TYPE, "Hoodat Q&A answer", "qa_answer", prompt, rendered_context, llm,
        guard_prompt=get_guard("hoodat", key),
    )
    value = _normalize_dialogue(_read_final_output(job_dir))
    return value, id_for("hoodat", key), _job_id_from_dir(job_dir)


async def run_qa_question(
    character_id: str,
    pairs: Optional[list[dict]] = None,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[str, Optional[str], str]:
    """Suggest one fitting interview question for the character (the "suggest
    question" helper). Returns `(question, prompt_id, job_id)`; no persistence."""
    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    key = "qa.question"
    rendered_context = render_character_context(character)
    prompt = get_text("hoodat", key, variables={
        "character": rendered_context, "qa": _qa_text(pairs),
    })
    job_dir = await _run_single_step(
        QA_JOB_TYPE, "Hoodat Q&A question", "qa_question", prompt, rendered_context, llm,
    )
    value = _normalize_dialogue(_read_final_output(job_dir))
    return value, id_for("hoodat", key), _job_id_from_dir(job_dir)


# ---- shared single-step runner ---------------------------------------------

async def _run_single_step(
    job_type: str, title: str, step_id: str, prompt: str, rendered_context: str,
    llm: ChainLLMConfig, guard_prompt: Optional[str] = None,
) -> Path:
    """Create + execute a 1-step LLM chain; return its job_dir (caller reads
    `final_output.txt`). Shared by the dialogue/experience/outfit/Q&A generators.

    When `guard_prompt` is given, a SECOND LLM "guard" step is appended: the
    chain executor feeds its `{{previous}}` from the first step's output, the
    guard either passes that through or rewrites it, and the guard's output
    becomes `final_output.txt` (only `llm` steps mutate text_output; last wins).
    """
    steps = [_llm_step(1, step_id, title, prompt)]
    if guard_prompt:
        steps.append(_llm_step(2, "guard", "Guard", guard_prompt))
    request = ChainJobRequest(
        title=title, input=rendered_context, llm=llm, steps=steps,
    )
    status = create_job(job_type, request.model_dump(), request.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        raise GenerationError("job directory disappeared after creation")
    await execute_chain_job(job_id, job_dir, request)
    return job_dir


def _job_id_from_dir(job_dir: Path) -> str:
    return job_dir.name


# ---- experiences -----------------------------------------------------------

def _loads_object(raw: str) -> dict:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise GenerationError(f"expected JSON, got: {raw!r}") from exc
    if not isinstance(data, dict):
        raise GenerationError(f"expected a JSON object, got: {raw!r}")
    return data


def _normalize_experience(raw: str) -> dict:
    """Parse a generated experience into `{description, valence}`. Tolerant:
    coerce an unknown/missing valence to "positive" rather than erroring."""
    data = _loads_object(raw)
    description = str(data.get("description") or "").strip()
    if not description:
        raise GenerationError("experience description was empty")
    valence = "negative" if str(data.get("valence", "")).strip().lower() == "negative" else "positive"
    return {"description": description, "valence": valence}


async def run_experience_example(
    character_id: str,
    experiences: Optional[list[dict]] = None,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[dict, Optional[str], str]:
    """Generate one new experience from the character + prior `experiences`.

    Returns `({description, valence}, prompt_id, job_id)`. Does **not** persist —
    the frontend owns the list and PUTs it wholesale.
    """
    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    key = "experience.example"
    rendered_context = render_character_context(character)
    prior = experiences or []
    exp_text = "\n".join(
        f"- ({e.get('valence', 'positive')}) {e.get('description', '')}" for e in prior
    ) or "(none yet)"
    prompt = get_text("hoodat", key, variables={
        "character": rendered_context, "experiences": exp_text,
    })

    job_dir = await _run_single_step(
        EXPERIENCE_JOB_TYPE, "Hoodat experience", "experience", prompt, rendered_context, llm,
    )
    value = _normalize_experience(_read_final_output(job_dir))
    return value, id_for("hoodat", key), _job_id_from_dir(job_dir)


# ---- outfits ---------------------------------------------------------------

def _outfit_text(outfit: Optional[dict]) -> str:
    """Render a partial outfit dict into readable text for prompt context."""
    outfit = outfit or {}
    parts = [f"{slot}: {outfit.get(slot)}" for slot in OUTFIT_SLOTS if str(outfit.get(slot) or "").strip()]
    name = str(outfit.get("name") or "").strip()
    head = f"name: {name}\n" if name else ""
    return head + ("\n".join(parts) if parts else "(empty so far)")


def _outfits_text(outfits: Optional[list[dict]]) -> str:
    items = outfits or []
    if not items:
        return "(none yet)"
    return "\n".join(f"{i}. {(o.get('name') or 'Outfit')}" for i, o in enumerate(items, 1))


def _normalize_outfit(raw: str) -> dict:
    """Parse a generated full outfit into `{name, <slots...>}` (no `primary`;
    the frontend owns that flag). Missing keys become empty strings."""
    data = _loads_object(raw)
    out = {"name": str(data.get("name") or "").strip()}
    for slot in OUTFIT_SLOTS:
        out[slot] = str(data.get(slot) or "").strip()
    return out


async def run_outfit(
    character_id: str,
    outfits: Optional[list[dict]] = None,
    outfit: Optional[dict] = None,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[dict, Optional[str], str]:
    """Generate a complete outfit (all garment slots). Returns
    `(outfit_dict, prompt_id, job_id)`; no persistence (frontend owns the list)."""
    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    key = "outfit.full"
    rendered_context = render_character_context(character)
    prompt = get_text("hoodat", key, variables={
        "character": rendered_context, "outfits": _outfits_text(outfits),
    })
    job_dir = await _run_single_step(
        OUTFIT_JOB_TYPE, "Hoodat outfit", "outfit", prompt, rendered_context, llm,
    )
    value = _normalize_outfit(_read_final_output(job_dir))
    return value, id_for("hoodat", key), _job_id_from_dir(job_dir)


async def run_outfit_slot(
    character_id: str,
    slot: str,
    outfit: Optional[dict] = None,
    outfits: Optional[list[dict]] = None,
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[str, Optional[str], str]:
    """Generate one garment slot value. Returns `(value, prompt_id, job_id)`."""
    if slot not in OUTFIT_SLOTS:
        raise GenerationError(f"unknown outfit slot: {slot!r}")
    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    key = "outfit.slot"
    rendered_context = render_character_context(character)
    prompt = get_text("hoodat", key, variables={
        "character": rendered_context, "outfit": _outfit_text(outfit), "slot": slot,
    })
    job_dir = await _run_single_step(
        OUTFIT_JOB_TYPE, f"Hoodat outfit slot {slot}", "outfit_slot", prompt, rendered_context, llm,
    )
    value = _normalize_value(_read_final_output(job_dir), "scalar")
    return value, id_for("hoodat", key), _job_id_from_dir(job_dir)
