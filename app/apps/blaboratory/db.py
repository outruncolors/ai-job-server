"""SQLite persistence for Blaboratory's simulation log.

The event/memory log is append-heavy and query-driven, so it lives in SQLite
(`config/blaboratory/blaboratory.db`) rather than the file-per-document JSON
stores used for config-like data (residents, occupancy). This module owns the
*connection* and the schema *migrations*; the per-table query helpers live in
sibling modules (`event_store`, `chat_store`, `cursor_store`).

Migrations are keyed by `PRAGMA user_version`: `MIGRATIONS[i]` upgrades the db
from version `i` to `i+1`. `migrate()` applies every pending migration in order,
each in its own transaction, and is idempotent. It runs lazily on the first
`get_connection()` and is also called explicitly at startup.

`DB_PATH` is a module-level constant so tests can monkeypatch it at a tmp path;
the cached connection is transparently reopened when the path changes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH: Path = PROJECT_ROOT / "config" / "blaboratory" / "blaboratory.db"

# Cached connection + the path it was opened for, so a monkeypatched DB_PATH
# (tests) transparently triggers a reopen.
_conn: Optional[sqlite3.Connection] = None
_conn_path: Optional[str] = None


def get_connection() -> sqlite3.Connection:
    """Return the shared connection for the current ``DB_PATH``.

    Opens (creating the parent dir) on first use or whenever ``DB_PATH`` has
    changed since the last open, applies pending migrations, and returns the
    cached handle. ``row_factory`` is ``sqlite3.Row`` so callers get mapping
    access.
    """
    global _conn, _conn_path
    target = str(DB_PATH)
    if _conn is not None and _conn_path == target:
        return _conn
    if _conn is not None:
        _conn.close()
        _conn = None
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the single connection is shared between the event
    # loop thread (async routes) and worker/threadpool threads. Access is
    # effectively serialized (one queue worker; handlers await on one loop), and
    # sqlite serializes statements on the connection, so this is safe here.
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _conn = conn
    _conn_path = target
    migrate(conn)
    return conn


def close_connection() -> None:
    """Close and forget the cached connection (test hook / shutdown)."""
    global _conn, _conn_path
    if _conn is not None:
        _conn.close()
    _conn = None
    _conn_path = None


# ---- migrations ----------------------------------------------------------


def _migration_1(conn: sqlite3.Connection) -> None:
    """Initial schema: the simulation event/memory log."""
    conn.executescript(
        """
        CREATE TABLE events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tick        INTEGER NOT NULL,
            resident_id TEXT,
            room_id     INTEGER,
            kind        TEXT NOT NULL,
            action      TEXT,
            payload     TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX idx_events_resident ON events(resident_id, id);
        CREATE INDEX idx_events_room     ON events(room_id, id);
        CREATE INDEX idx_events_tick     ON events(tick);

        CREATE TABLE chat (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            tick              INTEGER NOT NULL,
            author_resident_id TEXT,
            body              TEXT NOT NULL,
            created_at        TEXT NOT NULL
        );

        CREATE TABLE utterances (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id             INTEGER,
            tick                INTEGER NOT NULL,
            speaker_resident_id TEXT,
            room_id             INTEGER,
            body                TEXT NOT NULL,
            seq                 INTEGER NOT NULL,
            created_at          TEXT NOT NULL
        );
        CREATE INDEX idx_utterances_call ON utterances(call_id, seq);
        CREATE INDEX idx_utterances_room ON utterances(room_id, id);

        CREATE TABLE calls (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            tick               INTEGER NOT NULL,
            caller_resident_id TEXT NOT NULL,
            callee_resident_id TEXT NOT NULL,
            accepted           INTEGER NOT NULL,
            ended_reason       TEXT,
            created_at         TEXT NOT NULL
        );

        CREATE TABLE consumption_cursors (
            resident_id  TEXT NOT NULL,
            channel      TEXT NOT NULL,
            last_seen_id INTEGER NOT NULL DEFAULT 0,
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (resident_id, channel)
        );
        """
    )


# MIGRATIONS[i] upgrades the schema from user_version i to i+1.
MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_1,
]


def migrate(conn: Optional[sqlite3.Connection] = None) -> int:
    """Apply all pending migrations; return the resulting ``user_version``.

    Idempotent — a no-op when already at the latest version. Each migration runs
    in its own transaction so a failure leaves the db at the last good version.
    """
    if conn is None:
        conn = get_connection()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    while version < len(MIGRATIONS):
        with conn:  # transaction
            MIGRATIONS[version](conn)
            conn.execute(f"PRAGMA user_version = {version + 1}")
        version += 1
    return version
