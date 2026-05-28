"""Embed Lab playground SQLite database.

A standalone scratch space for embedding/retrieval experiments — fully decoupled
from blaboratory.db so manual testing can't pollute (or be polluted by) the sim.
Loads the sqlite-vec extension and owns a tiny two-table schema:

  docs (id INTEGER PK, text TEXT, created_at TEXT)
  vec_docs (vec0: embedding float[384], doc_id INTEGER)  -- only if vec available

The `vec_docs` vtable is created lazily on first `get_connection()` so the module
can boot on hosts where sqlite-vec failed to load (the same degrade-gracefully
posture the blaboratory db uses).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("config/embed-lab/playground.db")
EMBEDDING_DIM = 384

VEC_AVAILABLE: bool = False
_vec_load_logged: bool = False
_conn: Optional[sqlite3.Connection] = None
_vtable_ready: bool = False


def _load_vec_extension(conn: sqlite3.Connection) -> None:
    """Best-effort load of sqlite-vec into this connection. Sets VEC_AVAILABLE."""
    global VEC_AVAILABLE, _vec_load_logged
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        VEC_AVAILABLE = True
    except Exception as e:  # pragma: no cover - install-dependent
        VEC_AVAILABLE = False
        if not _vec_load_logged:
            logger.warning("embed_lab: sqlite-vec unavailable (%s) — retrieval disabled", e)
            _vec_load_logged = True


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create docs table + (if vec is available) the vec0 vtable. Idempotent."""
    global _vtable_ready
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    if VEC_AVAILABLE and not _vtable_ready:
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_docs USING vec0(
                embedding float[{EMBEDDING_DIM}],
                doc_id integer
            )
            """
        )
        conn.commit()
        _vtable_ready = True


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _load_vec_extension(conn)
    _ensure_schema(conn)
    _conn = conn
    return conn


def reset_connection() -> None:
    """Test-only: drop the cached connection so a fresh DB_PATH is reopened."""
    global _conn, _vtable_ready
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None
    _vtable_ready = False
