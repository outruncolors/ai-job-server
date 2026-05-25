"""Query/append helpers over the ``calls`` and ``utterances`` tables.

A phone call is one ``calls`` row plus an ordered set of ``utterances`` (one per
line spoken). Utterances carry a ``room_id`` so a call's lines surface in *both*
participants' rooms (the caller writes each line twice — once per room — see
Phase 6). Populated by the phone-call sequence in Phase 6; the query helpers
exist now so the API can range over them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .db import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_call(
    *, tick: int, caller_resident_id: str, callee_resident_id: str, accepted: bool
) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO calls (tick, caller_resident_id, callee_resident_id, accepted, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tick, caller_resident_id, callee_resident_id, int(accepted), _now_iso()),
        )
    return int(cur.lastrowid)


def end_call(call_id: int, ended_reason: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute("UPDATE calls SET ended_reason = ? WHERE id = ?", (ended_reason, call_id))


def append_utterance(
    *, call_id: int, tick: int, speaker_resident_id: str, room_id: int, body: str, seq: int
) -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO utterances (call_id, tick, speaker_resident_id, room_id, body, seq, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (call_id, tick, speaker_resident_id, room_id, body, seq, _now_iso()),
        )
    return int(cur.lastrowid)


def utterances_for_call(call_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM utterances WHERE call_id = ? ORDER BY seq ASC, id ASC", (call_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def utterances_for_room(room_id: int, *, until_tick: Optional[int] = None) -> list[dict]:
    """Utterances surfaced in a room, newest-first (truncated at ``until_tick``)."""
    conn = get_connection()
    sql = "SELECT * FROM utterances WHERE room_id = ?"
    params: list[Any] = [room_id]
    if until_tick is not None:
        sql += " AND tick <= ?"
        params.append(until_tick)
    sql += " ORDER BY id DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
