"""File-per-conversation store for Prattletale.

Each conversation is a folder ``config/prattletale/conversations/<id>/`` holding:

- ``conversation.json`` — metadata (a :class:`~app.apps.prattletale.models.Conversation`),
- ``transcript.json`` — the ordered turn log (a :class:`~app.apps.prattletale.models.Transcript`),
- ``traces/<turn>.json`` — per-model-turn debug capture (written by the generator),
- ``media/<item>.wav`` — generated audio (SP6 onward; absent in text-first phase).

Writes are atomic (``tmp`` + :func:`os.replace`). ``id`` is a slug derived from
the title, made unique against existing folder names (reusing
``slugify``/``unique_id`` from :mod:`app.cruddables.envelope`). Append/replace ops
**re-read** the transcript before writing so concurrent posts to one conversation
don't clobber each other. Turn ids are ``t%04d`` (via ``next_turn_seq``); item
ids are ``<turn_id>-i%02d``.

Tests monkeypatch :data:`CONVERSATIONS_DIR` to a tmp path.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from app.cruddables.envelope import now_iso, slugify, unique_id

from .models import (
    Author,
    Conversation,
    Item,
    ItemStatus,
    ItemType,
    Transcript,
    Turn,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONVERSATIONS_DIR: Path = PROJECT_ROOT / "config" / "prattletale" / "conversations"


# --- low-level io ----------------------------------------------------------

def _dir_for(conversation_id: str) -> Path:
    return CONVERSATIONS_DIR / conversation_id


def _conversation_path(conversation_id: str) -> Path:
    return _dir_for(conversation_id) / "conversation.json"


def _transcript_path(conversation_id: str) -> Path:
    return _dir_for(conversation_id) / "transcript.json"


def _trace_path(conversation_id: str, turn_id: str) -> Path:
    return _dir_for(conversation_id) / "traces" / f"{turn_id}.json"


def media_dir(conversation_id: str) -> Path:
    """The conversation's ``media/`` folder (generated audio). May not exist yet."""
    return _dir_for(conversation_id) / "media"


def media_file(conversation_id: str, filename: str) -> Path:
    """Path to a single media file. ``filename`` is the bare basename (the router
    rejects separators), so this can't escape the conversation folder."""
    return media_dir(conversation_id) / filename


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _taken_ids() -> set[str]:
    if not CONVERSATIONS_DIR.exists():
        return set()
    return {p.name for p in CONVERSATIONS_DIR.iterdir() if p.is_dir()}


# --- id formatters ---------------------------------------------------------

def _turn_id(seq: int) -> str:
    return f"t{seq:04d}"


def _item_id(turn_id: str, idx: int) -> str:
    """Item id format — explicit so traces and the frontend agree (``<turn_id>-i<NN>``)."""
    return f"{turn_id}-i{idx:02d}"


# --- conversation CRUD -----------------------------------------------------

def list_conversations() -> list[dict]:
    """All conversations as summary dicts (id, title, counterpart, last-item preview, updated_at)."""
    if not CONVERSATIONS_DIR.exists():
        return []
    summaries: list[dict] = []
    for d in CONVERSATIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        conv_path = d / "conversation.json"
        if not conv_path.exists():
            continue
        conv = _load(conv_path)
        summaries.append(
            {
                "id": conv.get("id"),
                "title": conv.get("title"),
                "counterpart_character_id": conv.get("counterpart_character_id"),
                "last_item_preview": _last_item_preview(conv.get("id")),
                "updated_at": conv.get("updated_at"),
            }
        )
    return summaries


def _last_item_preview(conversation_id: str) -> Optional[str]:
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    for turn in reversed(transcript.get("turns", [])):
        items = turn.get("items") or []
        if items:
            return items[-1].get("text")
    return None


def get_conversation(conversation_id: str) -> Optional[dict]:
    p = _conversation_path(conversation_id)
    if not p.exists():
        return None
    return _load(p)


def create_conversation(fields: dict) -> dict:
    """Create a conversation from ``fields``, assigning a unique slug id, timestamps,
    and writing both ``conversation.json`` and an empty ``transcript.json``. Returns
    the conversation dict.
    """
    now = now_iso()
    doc = dict(fields)
    doc["id"] = unique_id(slugify(doc.get("title") or "conversation"), _taken_ids())
    doc["created_at"] = now
    doc["updated_at"] = now
    conversation = Conversation(**doc)

    _atomic_write(_conversation_path(conversation.id), conversation.model_dump())
    transcript = Transcript(conversation_id=conversation.id)
    _atomic_write(_transcript_path(conversation.id), transcript.model_dump())
    return conversation.model_dump()


def update_conversation(conversation_id: str, patch: dict) -> Optional[dict]:
    """Shallow-merge ``patch`` into the conversation and persist (bumps ``updated_at``).
    None if the conversation is missing.
    """
    current = get_conversation(conversation_id)
    if current is None:
        return None
    current.update(patch)
    current["updated_at"] = now_iso()
    conversation = Conversation(**current)
    _atomic_write(_conversation_path(conversation_id), conversation.model_dump())
    return conversation.model_dump()


def delete_conversation(conversation_id: str) -> bool:
    d = _dir_for(conversation_id)
    if not d.exists():
        return False
    shutil.rmtree(d)
    return True


def _touch_conversation(conversation_id: str) -> None:
    """Bump the conversation's ``updated_at`` so list summaries reflect activity."""
    conv = get_conversation(conversation_id)
    if conv is None:
        return
    conv["updated_at"] = now_iso()
    _atomic_write(_conversation_path(conversation_id), conv)


# --- transcript ops --------------------------------------------------------

def _read_transcript(conversation_id: str) -> Optional[dict]:
    p = _transcript_path(conversation_id)
    if not p.exists():
        return None
    return _load(p)


def get_transcript(conversation_id: str) -> Optional[dict]:
    return _read_transcript(conversation_id)


def _build_items(turn_id: str, author: Author, items: list[dict], *, status: ItemStatus) -> list[dict]:
    """Turn caller-supplied ``{type, text, hidden_from_context?}`` dicts into full items."""
    now = now_iso()
    built: list[dict] = []
    for idx, raw in enumerate(items, start=1):
        item = Item(
            id=_item_id(turn_id, idx),
            turn_id=turn_id,
            author=author,
            type=ItemType(raw["type"]),
            text=raw.get("text", ""),
            status=status,
            audio=raw.get("audio"),
            hidden_from_context=bool(raw.get("hidden_from_context", False)),
            created_at=now,
        )
        built.append(item.model_dump(mode="json"))
    return built


def _append_turn(
    conversation_id: str,
    author: Author,
    items: list[dict],
    *,
    status: ItemStatus,
    job_id: Optional[str] = None,
) -> Optional[dict]:
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    seq = transcript.get("next_turn_seq", 1)
    turn_id = _turn_id(seq)
    turn = Turn(
        id=turn_id,
        author=author,
        created_at=now_iso(),
        job_id=job_id,
        items=_build_items(turn_id, author, items, status=status),
    )
    transcript.setdefault("turns", []).append(turn.model_dump(mode="json"))
    transcript["next_turn_seq"] = seq + 1
    _atomic_write(_transcript_path(conversation_id), transcript)
    _touch_conversation(conversation_id)
    return turn.model_dump(mode="json")


def append_user_turn(conversation_id: str, items: list[dict]) -> Optional[dict]:
    return _append_turn(conversation_id, Author.user, items, status=ItemStatus.committed)


def append_model_turn(conversation_id: str, items: list[dict], *, job_id: Optional[str] = None) -> Optional[dict]:
    return _append_turn(
        conversation_id, Author.model, items, status=ItemStatus.committed, job_id=job_id
    )


def append_error_turn(conversation_id: str, message: str, *, job_id: Optional[str] = None) -> Optional[dict]:
    """Append a model turn with a single ``system_error`` item (status ``error``)."""
    return _append_turn(
        conversation_id,
        Author.model,
        [{"type": ItemType.system_error.value, "text": message}],
        status=ItemStatus.error,
        job_id=job_id,
    )


def append_summary_turn(conversation_id: str, text: str) -> Optional[dict]:
    """Append a **system**-authored turn carrying one ``summary`` item.

    Used by the Summarizer plugin: a recap of earlier turns, rendered as an
    avatar-less centered card and kept in context (the compressed history). None
    if the conversation is missing."""
    return _append_turn(
        conversation_id,
        Author.system,
        [{"type": ItemType.summary.value, "text": text}],
        status=ItemStatus.committed,
    )


def replace_turn(
    conversation_id: str,
    turn_id: str,
    items: list[dict],
    *,
    author: Author = Author.model,
    job_id: Optional[str] = None,
) -> Optional[dict]:
    """Overwrite an existing turn **in place** — same ``turn_id`` and ``created_at``,
    new items (status ``committed``). Used by Retry so turn order/layout stays stable.
    None if the conversation or turn is missing.
    """
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    turns = transcript.get("turns", [])
    for i, turn in enumerate(turns):
        if turn.get("id") == turn_id:
            replacement = Turn(
                id=turn_id,
                author=Author(author),
                created_at=turn.get("created_at") or now_iso(),
                job_id=job_id,
                items=_build_items(turn_id, Author(author), items, status=ItemStatus.committed),
            )
            turns[i] = replacement.model_dump(mode="json")
            _atomic_write(_transcript_path(conversation_id), transcript)
            _touch_conversation(conversation_id)
            return replacement.model_dump(mode="json")
    return None


def apply_audio(conversation_id: str, turn_id: str, audio_by_item_id: dict) -> Optional[dict]:
    """Set ``audio`` on items of an existing turn **in place** (ids/text unchanged).

    Used by the voice stage: the model turn is committed text-first (so a synth
    failure can't lose the reply), then audio is attached once the wavs exist.
    Returns the updated turn, or None if the conversation/turn is missing.
    """
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    for turn in transcript.get("turns", []):
        if turn.get("id") == turn_id:
            for item in turn.get("items", []):
                if item.get("id") in audio_by_item_id:
                    item["audio"] = audio_by_item_id[item["id"]]
            _atomic_write(_transcript_path(conversation_id), transcript)
            return turn
    return None


def apply_sfx(conversation_id: str, turn_id: str, sfx_by_item_id: dict) -> Optional[dict]:
    """Set the ``sfx`` descriptor on items of an existing turn in place.

    Mirrors :func:`apply_audio` for the SFX plugin: the resolver runs after the
    turn is committed and attaches one compact descriptor per resolved item.
    Returns the updated turn, or None if the conversation/turn is missing.
    """
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    for turn in transcript.get("turns", []):
        if turn.get("id") == turn_id:
            for item in turn.get("items", []):
                if item.get("id") in sfx_by_item_id:
                    item["sfx"] = sfx_by_item_id[item["id"]]
            _atomic_write(_transcript_path(conversation_id), transcript)
            return turn
    return None


# --- in-place item / turn edits (Phase 2 SP1) ------------------------------

def _find_turn(transcript: dict, turn_id: str) -> Optional[dict]:
    for turn in transcript.get("turns", []):
        if turn.get("id") == turn_id:
            return turn
    return None


def edit_item(conversation_id: str, turn_id: str, item_id: str, text: str) -> Optional[dict]:
    """Overwrite one item's ``text`` in place (id/type/audio/status unchanged).

    Returns the updated turn, or None if the conversation, turn, or item is
    missing. Re-reads before writing (concurrent-write safe), mirroring
    :func:`replace_turn`.
    """
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    turn = _find_turn(transcript, turn_id)
    if turn is None:
        return None
    item = next((it for it in turn.get("items", []) if it.get("id") == item_id), None)
    if item is None:
        return None
    item["text"] = text
    _atomic_write(_transcript_path(conversation_id), transcript)
    _touch_conversation(conversation_id)
    return turn


def set_item_hidden(conversation_id: str, turn_id: str, item_id: str, hidden: bool) -> Optional[dict]:
    """Set an item's ``hidden_from_context`` flag in place. Returns the updated
    turn, or None if the conversation, turn, or item is missing."""
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    turn = _find_turn(transcript, turn_id)
    if turn is None:
        return None
    item = next((it for it in turn.get("items", []) if it.get("id") == item_id), None)
    if item is None:
        return None
    item["hidden_from_context"] = bool(hidden)
    _atomic_write(_transcript_path(conversation_id), transcript)
    _touch_conversation(conversation_id)
    return turn


def delete_item(conversation_id: str, turn_id: str, item_id: str) -> Optional[dict]:
    """Drop one item from a turn. If the turn is left with **zero** items, the
    whole turn is removed and ``{"turn_deleted": turn_id}`` is returned; otherwise
    the updated turn is returned. None if the conversation, turn, or item is
    missing. Surviving turns/items are **not** renumbered (ids stay stable)."""
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return None
    turn = _find_turn(transcript, turn_id)
    if turn is None:
        return None
    items = turn.get("items", [])
    if not any(it.get("id") == item_id for it in items):
        return None
    remaining = [it for it in items if it.get("id") != item_id]
    if not remaining:
        transcript["turns"] = [t for t in transcript.get("turns", []) if t.get("id") != turn_id]
        _atomic_write(_transcript_path(conversation_id), transcript)
        _touch_conversation(conversation_id)
        return {"turn_deleted": turn_id}
    turn["items"] = remaining
    _atomic_write(_transcript_path(conversation_id), transcript)
    _touch_conversation(conversation_id)
    return turn


def delete_turn(conversation_id: str, turn_id: str) -> bool:
    """Remove a whole turn. Returns True if removed, False if the conversation or
    turn is missing. Surviving turns keep their ids (no renumbering)."""
    transcript = _read_transcript(conversation_id)
    if transcript is None:
        return False
    turns = transcript.get("turns", [])
    if not any(t.get("id") == turn_id for t in turns):
        return False
    transcript["turns"] = [t for t in turns if t.get("id") != turn_id]
    _atomic_write(_transcript_path(conversation_id), transcript)
    _touch_conversation(conversation_id)
    return True


def write_trace(conversation_id: str, turn_id: str, trace: dict) -> None:
    """Persist a per-model-turn debug capture at ``traces/<turn_id>.json``."""
    _atomic_write(_trace_path(conversation_id, turn_id), trace)


# --- trace read (Phase 2 SP3) ----------------------------------------------

def get_trace(conversation_id: str, turn_id: str) -> Optional[dict]:
    """Read ``traces/<turn_id>.json``. None if the trace (or conversation) is absent."""
    p = _trace_path(conversation_id, turn_id)
    if not p.exists():
        return None
    return _load(p)


def list_traces(conversation_id: str) -> list[str]:
    """Turn ids that have a trace on disk (sorted). Empty if none / no folder."""
    traces = _dir_for(conversation_id) / "traces"
    if not traces.exists():
        return []
    return sorted(p.stem for p in traces.iterdir() if p.suffix == ".json")
