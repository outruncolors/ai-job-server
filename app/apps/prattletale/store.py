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


def write_trace(conversation_id: str, turn_id: str, trace: dict) -> None:
    """Persist a per-model-turn debug capture at ``traces/<turn_id>.json``."""
    _atomic_write(_trace_path(conversation_id, turn_id), trace)
