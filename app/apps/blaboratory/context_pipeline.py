"""Memory / context pipeline — the read → act → write loop's read & write halves.

Before a resident acts we assemble a fixed-section context **block** (read);
after it acts we persist the result and advance consumption cursors (write).
Retrieval is **mechanical** for now: gather the resident's consumed memories
newest-first, then apply recency/size caps. The vector index (deferred) will
later swap relevance retrieval in behind ``gather_memories``.

Context template — sections always render in this fixed order:

    [Overview]       static game/world framing + this resident's identity
    [Everyone Knows] shared world lore (read-only here; the news generator writes it)
    [Some Know]      scoped knowledge — DEFERRED, emitted empty (rule TBD)
    [You Know]       this resident's consumed memories (capped)
    [Your Action]    what they're doing now (an opaque pre-rendered string from the
                     action layer, so this module stays decoupled from Phase 4)

Visibility = consumption: ``[You Know]`` only contains chat the resident has
consumed (up to its cursor). Advancing a cursor — done in ``write_phase`` when an
action declares it consumed a channel — is what turns unseen events into memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import chat_store, cursor_store, event_store, settings_store

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Shared world lore registry (= [Everyone Knows]). Read here; the deferred news
# generator is what writes it. Stored as JSON: {"everyone_knows": "<text>"}.
LORE_PATH: Path = PROJECT_ROOT / "config" / "blaboratory" / "lore" / "world.json"

OVERVIEW_FRAMING = (
    "You are a resident living in Blaboratory, a quirky virtual laboratory full of "
    "eccentric inhabitants who pass the time on three channels: a shared computer "
    "chat, a televisor that broadcasts news, and a speakerphone for calling each other."
)


@dataclass
class Caps:
    # Resolved from settings at instantiation (per call) so an operator edit
    # applies on the next context build — no module-level constant to rebind.
    max_items: int = field(default_factory=settings_store.max_memory_items)
    max_chars: int = field(default_factory=settings_store.max_memory_chars)


# ---- section builders ----------------------------------------------------


def _identity_line(resident: dict) -> str:
    p = resident.get("personality") or {}
    traits = ", ".join(p.get("traits", []) or []) or "—"
    return (
        f"You are {resident.get('name', 'someone')}, "
        f"a {resident.get('age', '?')}-year-old {resident.get('sex', '')} "
        f"{resident.get('occupation', 'resident')}. "
        f"Notable traits: {traits}. "
        f"You speak in a {p.get('speech_style', 'plain')} manner."
    )


def read_lore() -> str:
    """The [Everyone Knows] lore text (empty string if none yet)."""
    if not LORE_PATH.exists():
        return ""
    try:
        data = json.loads(LORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    return data.get("everyone_knows", "") if isinstance(data, dict) else ""


def gather_memories(resident_id: str, caps: Optional[Caps] = None) -> list[str]:
    """Consumed memories for a resident, newest-first, before capping.

    Combines the resident's own event log with the chat it has consumed (up to
    its chat cursor). Mechanical recency gather — relevance retrieval is deferred.
    """
    lines: list[str] = []
    for ev in event_store.events_for_resident(resident_id):
        action = ev.get("action") or ev.get("kind")
        payload = ev.get("payload")
        detail = ""
        if isinstance(payload, dict):
            detail = payload.get("summary") or payload.get("text") or ""
        lines.append(f"[tick {ev['tick']}] you {action}" + (f": {detail}" if detail else ""))

    seen = cursor_store.get_cursor(resident_id, "chat")
    for msg in chat_store.chat_upto(seen):
        author = msg.get("author_resident_id") or "someone"
        lines.append(f"[tick {msg['tick']}] chat from {author}: {msg['body']}")
    return lines


def _build_query(recent: list[str]) -> str:
    """The retrieval query: the resident's recency window joined.

    "What's on my mind right now" — the most-recent items, embedded to pull
    older semantically-related memories beyond the recency floor.
    """
    return "\n".join(recent[: settings_store.recency_floor_items()])


async def retrieve_memories(resident: dict, caps: Optional[Caps] = None) -> list[str]:
    """Hybrid recent∪relevant memory retrieval for the ``[You Know]`` section.

    1. ``recent`` — the most-recent recency-floor consumed items, verbatim
       (the floor: a just-happened memory can never be evicted for irrelevance).
    2. ``relevant`` — top-k by similarity to the recency-window query, scoped to
       this resident (own events + their utterances + global lore) with chat
       limited to the consumption cursor, **minus** anything already in ``recent``.
    3. ``recent ++ relevant``, then :func:`apply_caps` (recent wins ties).

    Falls back to the **mechanical** capped gather — byte-identical to the
    pre-D1 behavior — when the vector extension is unavailable, nothing is
    indexed yet, or the embed server is unreachable. Never raises.
    """
    caps = caps or Caps()
    rid = resident["id"]
    full = gather_memories(rid, caps)
    if not full:
        return []

    # Lazy imports keep this module importable without the vector stack.
    from . import embeddings, memory_index, vector_index
    from .db import get_connection

    if not vector_index.is_available():
        return apply_caps(full, caps)
    # Nothing indexed yet → mechanical (and skip a pointless embed round-trip).
    conn = get_connection()
    if conn.execute("SELECT 1 FROM vec_memories LIMIT 1").fetchone() is None:
        return apply_caps(full, caps)

    try:
        qvecs = await embeddings.embed_texts([_build_query(full)], is_query=True)
    except embeddings.EmbedError:
        return apply_caps(full, caps)
    if not qvecs:
        return apply_caps(full, caps)

    recent = full[: settings_store.recency_floor_items()]
    recent_set = set(recent)
    seen = cursor_store.get_cursor(rid, "chat")
    hits = vector_index.query(
        qvecs[0],
        settings_store.relevant_top_k(),
        resident_id=rid,
        kinds=list(vector_index.KINDS),
        max_chat_id=seen,
    )
    relevant: list[str] = []
    for kind, ref_id, _dist in hits:
        line = memory_index.fetch_and_render(kind, ref_id)
        if line and line not in recent_set and line not in relevant:
            relevant.append(line)
    return apply_caps(recent + relevant, caps)


def apply_caps(items: list[str], caps: Optional[Caps] = None) -> list[str]:
    """Keep the newest items within both the item-count and char-budget caps.

    ``items`` is newest-first; over-cap drops the oldest (tail) first.
    """
    caps = caps or Caps()
    kept = items[: caps.max_items]
    total = 0
    out: list[str] = []
    for line in kept:
        total += len(line) + 1  # +1 for the join newline
        if total > caps.max_chars:
            break
        out.append(line)
    return out


async def build_context(
    resident: dict, *, action_node: str = "", tick: int = 0, caps: Optional[Caps] = None
) -> str:
    """Assemble the fixed-section context block for one resident on one tick."""
    caps = caps or Caps()
    you_know = await retrieve_memories(resident, caps)
    sections = [
        "[Overview]",
        f"{OVERVIEW_FRAMING}\n{_identity_line(resident)}",
        "",
        "[Everyone Knows]",
        read_lore(),
        "",
        "[Some Know]",
        "",  # DEFERRED — rule TBD
        "",
        "[You Know]",
        "\n".join(you_know) if you_know else "(nothing yet)",
        "",
        "[Your Action]",
        action_node,
    ]
    return "\n".join(sections).rstrip() + "\n"


# ---- read / write halves -------------------------------------------------


async def read_phase(
    resident: dict, tick: int, *, action_node: str = "", caps: Optional[Caps] = None
) -> str:
    """Read half: assemble the context block to feed the LLM."""
    return await build_context(resident, action_node=action_node, tick=tick, caps=caps)


def write_phase(resident: dict, tick: int, action_result: dict[str, Any]) -> int:
    """Write half: persist the action's outcome as memory and advance cursors.

    ``action_result`` is a plain dict produced by an action runner (Phase 4):
        {
          "action": str,                 # action name (e.g. "use_computer")
          "kind": str = "action",        # event kind
          "room_id": int | None,
          "payload": dict | None,        # action-specific detail
          "chat_post": str | None,       # if set, appended to the chat feed
          "consume": ["chat", ...],      # channels this action consumed
        }
    Returns the id of the event row written.
    """
    rid = resident["id"]

    post = action_result.get("chat_post")
    chat_id = None
    if post:
        chat_id = chat_store.append_chat(tick=tick, body=post, author_resident_id=rid)

    for channel in action_result.get("consume", []) or []:
        if channel == "chat":
            # Consumption advances to the latest id (incl. any post just made).
            cursor_store.set_cursor(rid, "chat", chat_store.latest_chat_id())
        elif channel == "news":
            news_id = action_result.get("news_seen_id")
            if news_id is not None:
                cursor_store.set_cursor(rid, "news", news_id)

    # Carry the chat row id into the event payload so the event log can deep-link
    # to the exact message in the Messages tab.
    payload = action_result.get("payload")
    if chat_id is not None:
        payload = dict(payload or {})
        payload["chat_id"] = chat_id

    return event_store.append_event(
        tick=tick,
        kind=action_result.get("kind", "action"),
        resident_id=rid,
        room_id=action_result.get("room_id"),
        action=action_result.get("action"),
        payload=payload,
    )
