"""The Remember plugin: registration + its ``remember`` and ``gist`` write actions.

This is the explicit, curated **write** half of Prattletale's memory integration
(retrieval lives in the turn chain via the ``{{memory}}`` token). Nothing here runs
automatically — every memory is written by a deliberate user action:

- ``remember`` — persist a fact the user typed (the 🧠 Remember composer mode) or a
  message verbatim (the per-bubble Memorize → Verbatim sub-action).
- ``gist`` — distill a highlighted message (+ a little surrounding context) into a
  durable note via a guarded Prompt Pal pass, then persist it (Memorize → Gist).

Both write through the memory **service** only (``get_service().write``), to the
``character:<counterpart>`` or ``session:<conversation>`` scope. A failed action
raises (dispatch maps :class:`ValueError` → 422, any other exception → 500); it
never posts a chat turn — the frontend surfaces the result as a toast.
"""

from __future__ import annotations

from typing import Optional

from app.apps.hoodat.characters_store import get_character
from app.apps.prattletale import store
from app.apps.prattletale.generator import (
    GenerationError,
    _flatten_transcript,
    _llm_step,
    _read_final_output,
    _resolve_llm,
)
from app.apps.prattletale.models import ItemType
from app.chain.executor import execute_chain_job
from app.chain.models import ChainJobRequest
from app.jobs import create_job, find_job_dir
from app.memory import MemoryScope, MemoryWriteRequest, get_service
from app.prompt_pal.service import get_guard, get_text

from ..base import Plugin
from ..registry import register
from . import prompts  # noqa: F401 — ensure memory.* Prompt Pal entries are registered

JOB_TYPE = "prattletale_memory_gist"

# How many recent turns to hand the Gist prompt as grounding context.
_GIST_CONTEXT_TURNS = 6

# Frontend assets, loaded by the page only when the plugin is enabled.
_FRONTEND = [
    "apps/prattletale/plugins/memory/memory.js",
    "apps/prattletale/plugins/memory/memory.css",
]


def _resolve_scope(conversation: dict, scope: str) -> MemoryScope:
    """Map the UI's scope choice onto a concrete memory scope. ``character`` (the
    default) persists across every chat with this counterpart — the cross-
    conversation recall the integration is meant to demonstrate; ``session`` pins
    the memory to this one conversation."""
    if scope == "session":
        return MemoryScope(scope_type="session", scope_id=conversation["id"])
    if scope in ("", "character"):
        return MemoryScope(scope_type="character", scope_id=conversation["counterpart_character_id"])
    raise ValueError(f"invalid scope: {scope!r} (expected 'character' or 'session')")


def _title_from(text: str) -> str:
    """A short, human title for the memory file — the first line, trimmed."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    first = first.strip()
    return (first[:77] + "…") if len(first) > 78 else (first or "Untitled memory")


async def _write(conversation: dict, text: str, scope: str, *, tags: list, source_type: str) -> dict:
    """Shared write path for both actions. Returns the frontend-facing result."""
    body = (text or "").strip()
    if not body:
        raise ValueError("nothing to remember (empty text)")
    resolved = _resolve_scope(conversation, scope)
    rec, _path = await get_service().write(
        MemoryWriteRequest(
            title=_title_from(body),
            body=body,
            scope=resolved,
            tags=[t for t in (tags or []) if isinstance(t, str) and t.strip()],
            source_type=source_type,
            source_ref=conversation["id"],
        )
    )
    return {"ok": True, "memory_id": rec.id, "scope": resolved.key(), "title": rec.title}


def _find_item_text(transcript: dict, turn_id: str, item_id: str) -> Optional[str]:
    for turn in transcript.get("turns") or []:
        if turn.get("id") != turn_id:
            continue
        for it in turn.get("items") or []:
            if it.get("id") == item_id:
                return (it.get("text") or "").strip()
    return None


def _recent_context(transcript: dict, turn_id: str, character: dict) -> str:
    """Flatten the window of turns ending at ``turn_id`` (inclusive) for grounding."""
    turns = transcript.get("turns") or []
    end = len(turns)
    for i, turn in enumerate(turns):
        if turn.get("id") == turn_id:
            end = i + 1
            break
    window = turns[max(0, end - _GIST_CONTEXT_TURNS):end]
    return _flatten_transcript(window, character)


async def run_remember(conversation_id: str, params: dict) -> dict:
    """Persist a user-supplied fact (composer Remember) or a verbatim message.

    ``params``: ``{text, scope: "character"|"session", tags?: list[str]}``."""
    text = params.get("text", "")
    scope = params.get("scope", "character")
    tags = params.get("tags") or []
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if not isinstance(tags, list):
        raise ValueError("tags must be a list")
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"conversation not found: {conversation_id}")
    return await _write(conversation, text, scope, tags=tags, source_type="prattletale")


async def run_gist(conversation_id: str, params: dict) -> dict:
    """Distill a highlighted message into a durable note, then persist it.

    ``params``: ``{turn_id, item_id, scope: "character"|"session"}``."""
    turn_id = params.get("turn_id", "")
    item_id = params.get("item_id", "")
    scope = params.get("scope", "character")
    if not turn_id or not item_id:
        raise ValueError("turn_id and item_id are required")

    conversation = store.get_conversation(conversation_id)
    transcript = store.get_transcript(conversation_id)
    if conversation is None or transcript is None:
        raise ValueError(f"conversation not found: {conversation_id}")
    character = get_character(conversation["counterpart_character_id"])
    if character is None:
        raise ValueError("counterpart character not found")

    message = _find_item_text(transcript, turn_id, item_id)
    if not message:
        raise ValueError(f"message not found: {turn_id}/{item_id}")

    context = _recent_context(transcript, turn_id, character)
    gist = await _run_gist_job(message, context)
    if not gist.strip():
        raise ValueError("could not distill a memory from this message")

    result = await _write(conversation, gist, scope, tags=["gist"], source_type="prattletale_gist")
    result["gist"] = gist
    return result


async def _run_gist_job(message: str, context: str) -> str:
    """Run the ``memory.gist`` prompt + its guard as a 2-step LLM chain and return
    ``final_output.txt`` (mirrors Hoodat's guarded single-step runner)."""
    variables = {"message": message, "context": context}
    prompt = get_text("prattletale", "memory.gist", variables=variables)
    steps = [_llm_step(1, "gist", "Gist", prompt)]
    guard_prompt = get_guard("prattletale", "memory.gist")
    if guard_prompt:
        steps.append(_llm_step(2, "guard", "Guard", guard_prompt))

    llm = _resolve_llm(None)
    request = ChainJobRequest(title="Memory gist", input=prompt, llm=llm, steps=steps)
    status = create_job(JOB_TYPE, request.model_dump(), request.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover — create_job just made it
        raise GenerationError("job directory disappeared after creation")
    await execute_chain_job(job_id, job_dir, request)
    return _read_final_output(job_dir).strip()


def _seed_prompts() -> None:
    """Seed the plugin's Prompt Pal entries (registered on import). Idempotent."""
    from app.prompt_pal.registry import seed_registered

    seed_registered()


plugin = Plugin(
    id="memory",
    name="Remember",
    description="Save curated facts to long-term memory (a typed note, a message verbatim, or a distilled gist).",
    frontend=_FRONTEND,
    actions={"remember": run_remember, "gist": run_gist},
    default_enabled=True,
    seed_prompts=_seed_prompts,
)

register(plugin)
