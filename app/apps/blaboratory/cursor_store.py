"""Per-resident consumption cursors.

Visibility = consumption: a resident only "knows" chat/news it has actively
consumed (via ``use_computer`` / ``use_televisor``). Each cursor records the
last-seen id on a channel; advancing it is what turns an unconsumed event into a
memory. ``channel`` is one of ``"chat"`` or ``"news"``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .db import get_connection

CHANNELS = ("chat", "news")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_cursor(resident_id: str, channel: str) -> int:
    """Last-seen id for a resident on a channel (0 if never set)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT last_seen_id FROM consumption_cursors WHERE resident_id = ? AND channel = ?",
        (resident_id, channel),
    ).fetchone()
    return int(row["last_seen_id"]) if row else 0


def set_cursor(resident_id: str, channel: str, last_seen_id: int) -> None:
    """Upsert the cursor for a resident/channel to ``last_seen_id``."""
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO consumption_cursors (resident_id, channel, last_seen_id, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(resident_id, channel) DO UPDATE SET "
            "last_seen_id = excluded.last_seen_id, updated_at = excluded.updated_at",
            (resident_id, channel, last_seen_id, _now_iso()),
        )
