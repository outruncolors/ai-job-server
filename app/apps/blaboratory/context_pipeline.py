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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import chat_store, cursor_store, event_store
from .config import MAX_MEMORY_CHARS, MAX_MEMORY_ITEMS

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
    max_items: int = MAX_MEMORY_ITEMS
    max_chars: int = MAX_MEMORY_CHARS


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


def build_context(
    resident: dict, *, action_node: str = "", tick: int = 0, caps: Optional[Caps] = None
) -> str:
    """Assemble the fixed-section context block for one resident on one tick."""
    caps = caps or Caps()
    you_know = apply_caps(gather_memories(resident["id"], caps), caps)
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


def read_phase(resident: dict, tick: int, *, action_node: str = "", caps: Optional[Caps] = None) -> str:
    """Read half: assemble the context block to feed the LLM."""
    return build_context(resident, action_node=action_node, tick=tick, caps=caps)


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
    if post:
        chat_store.append_chat(tick=tick, body=post, author_resident_id=rid)

    for channel in action_result.get("consume", []) or []:
        if channel == "chat":
            # Consumption advances to the latest id (incl. any post just made).
            cursor_store.set_cursor(rid, "chat", chat_store.latest_chat_id())
        elif channel == "news":
            news_id = action_result.get("news_seen_id")
            if news_id is not None:
                cursor_store.set_cursor(rid, "news", news_id)

    return event_store.append_event(
        tick=tick,
        kind=action_result.get("kind", "action"),
        resident_id=rid,
        room_id=action_result.get("room_id"),
        action=action_result.get("action"),
        payload=action_result.get("payload"),
    )
