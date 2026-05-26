"""Thin helper over the ``vec_memories`` vec0 virtual table (D1 retrieval).

Mirrors the per-table query-helper shape of ``event_store`` / ``chat_store``:
this module owns the *vector* reads/writes, ``db.py`` owns the connection and
the schema migration. All scoping (resident, kind, chat cursor) lives in the
``WHERE`` of the KNN query so the index returns only rows the reader may see.

The embedding dimension is fixed at 384 (bge-small-en-v1.5), baked into the
schema; callers pass plain ``list[float]`` and ``sqlite_vec.serialize_float32``
packs them. When sqlite-vec is unavailable (``db.VEC_AVAILABLE`` False) the
table doesn't exist — ``is_available()`` is False and ``add``/``query`` are
no-ops so retrieval degrades to mechanical recency instead of raising.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from . import db

EMBEDDING_DIM = 384

# Allowed kinds (kept here so callers/tests share one source of truth).
KINDS = ("event", "chat", "utterance", "lore")

# sqlite-vec 0.1.9 rejects NULL in TEXT/INTEGER metadata columns, so "global"
# (lore, owned by no resident) is stored as the empty string and surfaced back
# as None. Callers still pass/receive resident_id=None for global rows.
_GLOBAL = ""


def is_available() -> bool:
    """True when the vector store is usable (sqlite-vec loaded + migrated)."""
    return db.VEC_AVAILABLE


def _serialize(vec: list[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(vec)


def add(rows: Iterable[dict[str, Any]]) -> list[int]:
    """Insert embedded rows into the vector store; return their ``vec_id``s.

    Each row is a dict with keys ``embedding`` (``list[float]`` of length 384),
    ``resident_id`` (str | None — None = global/lore), ``kind``, ``ref_id``,
    ``tick``. Also records each in ``vec_rowmap`` keyed by ``(kind, ref_id)`` so
    re-indexing the same source row is detectable. No-op (returns ``[]``) when
    the extension is unavailable.
    """
    if not is_available():
        return []
    conn = db.get_connection()
    vec_ids: list[int] = []
    with conn:
        for row in rows:
            embedding = row["embedding"]
            if len(embedding) != EMBEDDING_DIM:
                raise ValueError(
                    f"embedding must have {EMBEDDING_DIM} dims, got {len(embedding)}"
                )
            cur = conn.execute(
                "INSERT INTO vec_memories (embedding, resident_id, kind, ref_id, tick) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _serialize(embedding),
                    row.get("resident_id") or _GLOBAL,
                    row["kind"],
                    row["ref_id"],
                    int(row.get("tick") or 0),
                ),
            )
            vec_id = int(cur.lastrowid)
            conn.execute(
                "INSERT OR REPLACE INTO vec_rowmap (kind, ref_id, vec_id) VALUES (?, ?, ?)",
                (row["kind"], row["ref_id"], vec_id),
            )
            vec_ids.append(vec_id)
    return vec_ids


def query(
    vec: list[float],
    k: int,
    *,
    resident_id: Optional[str] = None,
    kinds: Optional[Iterable[str]] = None,
    max_chat_id: Optional[int] = None,
) -> list[tuple[str, int, float]]:
    """K-nearest rows to ``vec``, nearest-first, as ``(kind, ref_id, distance)``.

    Scope filters, all applied inside the KNN ``WHERE`` so they prune before the
    k-limit:
    - ``resident_id`` — restrict to this resident's rows **plus** global rows
      (``resident_id IS NULL`` = lore), so lore is eligible for everyone.
    - ``kinds`` — restrict to ``kind IN (...)``.
    - ``max_chat_id`` — for chat rows only, require ``ref_id <= max_chat_id``
      (a range predicate honoring the reader's consumption cursor:
      visibility = consumption). Non-chat rows are unaffected.

    Returns ``[]`` when the extension is unavailable.
    """
    if not is_available():
        return []
    conn = db.get_connection()
    where = ["embedding MATCH ?", "k = ?"]
    params: list[Any] = [_serialize(vec), k]
    if resident_id is not None:
        # this resident's rows plus global rows (stored as the empty-string sentinel)
        where.append("(resident_id = ? OR resident_id = ?)")
        params.extend([resident_id, _GLOBAL])
    if kinds is not None:
        kinds = list(kinds)
        if not kinds:
            return []
        placeholders = ", ".join("?" for _ in kinds)
        where.append(f"kind IN ({placeholders})")
        params.extend(kinds)
    if max_chat_id is not None:
        where.append("(kind != 'chat' OR ref_id <= ?)")
        params.append(max_chat_id)
    sql = (
        "SELECT kind, ref_id, distance FROM vec_memories WHERE "
        + " AND ".join(where)
        + " ORDER BY distance"
    )
    return [
        (r["kind"], int(r["ref_id"]), float(r["distance"]))
        for r in conn.execute(sql, params).fetchall()
    ]
