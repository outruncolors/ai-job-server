"""Query helpers over the ``chat`` table — the shared computer-channel feed.

A single global feed of messages residents post via ``use_computer``. Visibility
is governed by per-resident consumption cursors (see ``cursor_store``), not by
the chat rows themselves; this module just appends and ranges.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_chat(*, tick: int, body: str, author_resident_id: Optional[str] = None) -> int:
    """Append a chat message; return its id."""
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO chat (tick, author_resident_id, body, created_at) VALUES (?, ?, ?, ?)",
            (tick, author_resident_id, body, _now_iso()),
        )
    return int(cur.lastrowid)


def chat_after(last_seen_id: int, *, limit: Optional[int] = None) -> list[dict]:
    """Chat messages with id > ``last_seen_id`` (the unconsumed tail), oldest-first."""
    conn = get_connection()
    sql = "SELECT * FROM chat WHERE id > ? ORDER BY id ASC"
    params: list[Any] = [last_seen_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def chat_upto(last_seen_id: int, *, limit: Optional[int] = None) -> list[dict]:
    """Chat messages with id <= ``last_seen_id`` (the consumed history), newest-first."""
    conn = get_connection()
    sql = "SELECT * FROM chat WHERE id <= ? ORDER BY id DESC"
    params: list[Any] = [last_seen_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def latest_chat_id() -> int:
    """The highest chat id, or 0 if the feed is empty."""
    conn = get_connection()
    row = conn.execute("SELECT MAX(id) AS m FROM chat").fetchone()
    return int(row["m"]) if row and row["m"] is not None else 0
