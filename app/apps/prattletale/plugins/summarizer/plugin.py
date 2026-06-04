"""The Summarizer plugin registration + its ``summarize`` action.

Wires SP2's engine into SP1's dispatch: the ``summarize`` action validates params,
runs :func:`summarize.summarize_history`, posts a single ``summary`` turn, and on
**Purge** hides the covered originals (so the summary compresses the context
window) — returning what the frontend needs to render in place.

A failed summarize raises (the dispatch maps :class:`ValueError` → 422, any other
exception → 500); it never posts a ``system_error`` chat turn — the panel surfaces
the error inline.
"""

from __future__ import annotations

from app.apps.hoodat.characters_store import get_character
from app.apps.prattletale import store
from app.apps.prattletale.models import ItemType

from ..base import Plugin
from ..registry import register
from . import summarize

# Frontend assets, loaded by the page only when the plugin is enabled (SP5
# delivers them). Paths are relative to ``static/``.
_FRONTEND = [
    "apps/prattletale/plugins/summarizer/summarizer.js",
    "apps/prattletale/plugins/summarizer/summarizer.css",
]


def _covered_item_ids(transcript: dict) -> list[tuple[str, str]]:
    """``(turn_id, item_id)`` for every item visible in context — the originals a
    summary covers (skips already-hidden + ``system_error`` items)."""
    out: list[tuple[str, str]] = []
    for turn in transcript.get("turns") or []:
        tid = turn.get("id")
        for it in turn.get("items") or []:
            if not it.get("hidden_from_context") and it.get("type") != ItemType.system_error.value:
                out.append((tid, it.get("id")))
    return out


async def run_summarize(conversation_id: str, params: dict) -> dict:
    """Validate, summarize, post the recap, optionally purge. Returns
    ``{summary_turn, hidden_item_ids, mode}`` (plus ``memory_id`` when remembered).

    ``params``: ``{mode: "keep"|"purge", detail: "brief"|"standard"|"detailed",
    focus: str, remember?: bool, remember_scope?: "character"|"session"}``. When
    ``remember`` is set the curated recap is *also* written to long-term memory via
    the Remember plugin's write path (so the recap recurs in future conversations).
    Bad values raise :class:`ValueError` (→ 422)."""
    mode = params.get("mode", "keep")
    detail = params.get("detail", "standard")
    focus = params.get("focus", "") or ""
    remember = bool(params.get("remember", False))
    remember_scope = params.get("remember_scope", "character")
    if mode not in ("keep", "purge"):
        raise ValueError(f"invalid mode: {mode!r} (expected 'keep' or 'purge')")
    if detail not in summarize.VALID_LEVELS:
        raise ValueError(f"invalid detail: {detail!r} (expected one of {summarize.VALID_LEVELS})")
    if not isinstance(focus, str):
        raise ValueError("focus must be a string")

    conversation = store.get_conversation(conversation_id)
    transcript = store.get_transcript(conversation_id)
    if conversation is None or transcript is None:
        raise ValueError(f"conversation not found: {conversation_id}")
    character = get_character(conversation["counterpart_character_id"])
    if character is None:
        raise ValueError("counterpart character not found")

    # Snapshot the covered originals BEFORE posting the new summary, so the recap
    # itself is never marked hidden.
    covered = _covered_item_ids(transcript)

    summary_text = await summarize.summarize_history(
        conversation, character, transcript, level=detail, focus=focus,
    )
    if not summary_text.strip():
        raise ValueError("nothing to summarize")

    summary_turn = store.append_summary_turn(conversation_id, summary_text)
    if summary_turn is None:  # pragma: no cover — conversation checked above
        raise ValueError("failed to persist summary turn")

    hidden_item_ids: list[str] = []
    if mode == "purge":
        for tid, iid in covered:
            store.set_item_hidden(conversation_id, tid, iid, True)
            hidden_item_ids.append(iid)

    result = {"summary_turn": summary_turn, "hidden_item_ids": hidden_item_ids, "mode": mode}
    if remember:
        # Reuse the Remember plugin's write path so the curated recap lands in the
        # same scopes the turn chain retrieves from (default: this character).
        from ..memory.plugin import _write  # local import avoids a plugin import cycle

        written = await _write(
            conversation, summary_text, remember_scope,
            tags=["summary"], source_type="prattletale_summary",
        )
        result["memory_id"] = written["memory_id"]
        result["memory_scope"] = written["scope"]
    return result


def _seed_prompts() -> None:
    """Seed the summarizer's Prompt Pal entries (the ``prompts`` module's
    register() ran on import). Seed-if-absent, idempotent."""
    from app.prompt_pal.registry import seed_registered

    seed_registered()


plugin = Plugin(
    id="summarizer",
    name="Summarizer",
    description="Condense the conversation so far into a single recap (Keep or Purge).",
    frontend=_FRONTEND,
    actions={"summarize": run_summarize},
    default_enabled=True,
    seed_prompts=_seed_prompts,
)

register(plugin)
