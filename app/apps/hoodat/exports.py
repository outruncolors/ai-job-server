"""Targeted Exports for Hoodat.

An *export* is a user-authored prompt that receives the full character document
and renders it at a configurable level of detail — for piping a character into
other contexts. Export prompts are **Prompt Pal entries** (app="hoodat", key
`export.<slug>`) so they are created/edited/listed through Prompt Pal — no
separate store. Running one is a single LLM chain over the rendered character.
"""

from __future__ import annotations

from typing import Optional

from ...chain.executor import execute_chain_job
from ...chain.models import Alternative, ChainJobRequest, ChainLLMConfig, ChainStep
from ...jobs import create_job, find_job_dir
from ...prompt_pal import store as pp_store
from ...prompt_pal.service import get_text
from . import characters_store
from .generator import GenerationError, _read_final_output, _resolve_llm
from .prompts import render_character_context

EXPORT_JOB_TYPE = "hoodat_export"
EXPORT_PREFIX = "export."
DETAIL_LEVELS = ("brief", "standard", "detailed")


def list_exports() -> list[dict]:
    """All Hoodat export-prompt entries (Prompt Pal entries keyed `export.*`)."""
    return [
        e for e in pp_store.list_entries()
        if e.get("app") == "hoodat" and str(e.get("key", "")).startswith(EXPORT_PREFIX)
    ]


async def run_export(
    character_id: str,
    export_key: str,
    detail: str = "standard",
    llm: Optional[ChainLLMConfig] = None,
) -> tuple[str, str]:
    """Run an export prompt over a character. Returns `(text, job_id)`."""
    if detail not in DETAIL_LEVELS:
        raise GenerationError(f"unknown detail level: {detail!r}")
    if not export_key.startswith(EXPORT_PREFIX):
        raise GenerationError(f"not an export prompt: {export_key!r}")
    if pp_store.get_by_app_key("hoodat", export_key) is None:
        raise GenerationError(f"export not found: {export_key!r}")

    character = characters_store.get_character(character_id)
    if character is None:
        raise GenerationError(f"character not found: {character_id}")

    llm = _resolve_llm(llm)
    rendered = render_character_context(character)
    examples = ((character.get("speaking_style") or {}).get("dialogue_examples")) or []
    examples_text = "\n".join(f"- {e}" for e in examples)
    prompt = get_text("hoodat", export_key, variables={
        "character": rendered, "detail": detail, "dialogue_examples": examples_text,
    })

    request = ChainJobRequest(
        title=f"Hoodat export {export_key}",
        input=rendered,
        llm=llm,
        steps=[ChainStep(number=1, id="export", name="Export", type="llm",
                         alternatives=[Alternative(prompt=prompt)])],
    )
    status = create_job(EXPORT_JOB_TYPE, request.model_dump(), request.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        raise GenerationError("job directory disappeared after creation")

    await execute_chain_job(job_id, job_dir, request)
    return _read_final_output(job_dir), job_id
