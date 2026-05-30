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


# ---- UI feed paging ------------------------------------------------------
# Playhead-scoped helpers for the Messages tab. All return rows *oldest-first*
# (ascending id) so the frontend can prepend/append uniformly. Separate from the
# consumption-cursor helpers above (which the context pipeline depends on).


def _scope(sql: str, params: list[Any], until_tick: Optional[int]) -> str:
    """Append a playhead bound (``tick <= until_tick``) when set."""
    if until_tick is not None:
        sql += " AND tick <= ?"
        params.append(until_tick)
    return sql


def chat_latest(*, until_tick: Optional[int] = None, limit: int = 50) -> list[dict]:
    """The newest ``limit`` messages (tick-scoped), returned oldest-first."""
    conn = get_connection()
    params: list[Any] = []
    sql = _scope("SELECT * FROM chat WHERE 1=1", params, until_tick)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    rows.reverse()
    return rows


def chat_before(before_id: int, *, until_tick: Optional[int] = None, limit: int = 50) -> list[dict]:
    """The ``limit`` messages with id < ``before_id`` (older page), oldest-first."""
    conn = get_connection()
    params: list[Any] = [before_id]
    sql = _scope("SELECT * FROM chat WHERE id < ?", params, until_tick)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    rows.reverse()
    return rows


def chat_newer(after_id: int, *, until_tick: Optional[int] = None, limit: int = 50) -> list[dict]:
    """The ``limit`` messages with id > ``after_id`` (newer page), oldest-first."""
    conn = get_connection()
    params: list[Any] = [after_id]
    sql = _scope("SELECT * FROM chat WHERE id > ?", params, until_tick)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_chat(message_id: int) -> Optional[dict]:
    """A single chat message by id, or None."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM chat WHERE id = ?", (message_id,)).fetchone()
    return dict(row) if row else None
