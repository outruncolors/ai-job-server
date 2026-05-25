"""Query helpers over the ``events`` table (the master simulation log).

One row per action / utterance / system event. ``payload`` carries
action-specific detail as a JSON string; ``append_event`` accepts a dict and
``_row_to_dict`` decodes it back. All reads return plain dicts (newest-first
where ordering matters) so callers never touch ``sqlite3.Row``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from .db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    d = dict(row)
    raw = d.get("payload")
    d["payload"] = json.loads(raw) if raw else None
    return d


def append_event(
    *,
    tick: int,
    kind: str,
    resident_id: Optional[str] = None,
    room_id: Optional[int] = None,
    action: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> int:
    """Append one event row; return its autoincrement id."""
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO events (tick, resident_id, room_id, kind, action, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                tick,
                resident_id,
                room_id,
                kind,
                action,
                json.dumps(payload) if payload is not None else None,
                _now_iso(),
            ),
        )
    return int(cur.lastrowid)


def events_for_resident(
    resident_id: str, *, until_tick: Optional[int] = None, limit: Optional[int] = None
) -> list[dict]:
    """Events for one resident, newest-first. ``until_tick`` truncates at the
    playhead (events at tick <= until_tick)."""
    conn = get_connection()
    sql = "SELECT * FROM events WHERE resident_id = ?"
    params: list[Any] = [resident_id]
    if until_tick is not None:
        sql += " AND tick <= ?"
        params.append(until_tick)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def events_for_room(
    room_id: int, *, until_tick: Optional[int] = None, limit: Optional[int] = None
) -> list[dict]:
    """Events in one room, newest-first."""
    conn = get_connection()
    sql = "SELECT * FROM events WHERE room_id = ?"
    params: list[Any] = [room_id]
    if until_tick is not None:
        sql += " AND tick <= ?"
        params.append(until_tick)
    sql += " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def events_at_tick(tick: int) -> list[dict]:
    """All events recorded at a given tick, oldest-first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM events WHERE tick = ? ORDER BY id ASC", (tick,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def latest_event_for_room(room_id: int, *, until_tick: Optional[int] = None) -> Optional[dict]:
    """The most recent event in a room (at/under ``until_tick`` if given), or None."""
    rows = events_for_room(room_id, until_tick=until_tick, limit=1)
    return rows[0] if rows else None


def max_tick() -> int:
    """The highest tick recorded, or 0 if the log is empty."""
    conn = get_connection()
    row = conn.execute("SELECT MAX(tick) AS m FROM events").fetchone()
    return int(row["m"]) if row and row["m"] is not None else 0
