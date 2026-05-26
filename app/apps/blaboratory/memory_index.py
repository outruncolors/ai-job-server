"""Indexing pipeline — batch backfill of the vector store (D1.3).

Once per tick (before the gather) we embed every memory-bearing row that isn't
in the index yet and store its vector. This keeps embed calls **out** of the
synchronous ``write_phase``: writes stay cheap, indexing is an idempotent
catch-up pass that also picks up rows authored by others and backfills after an
embed outage.

"Un-indexed" = a source row (events / chat / utterances) with no matching
``(kind, ref_id)`` in ``vec_rowmap`` (a LEFT JOIN). The rendered text mirrors
``context_pipeline.gather_memories`` so what we index is what a resident reads.

Scoping written into ``vec_memories`` (so D1.4 retrieval can filter):
- ``event``     → the event's ``resident_id`` (None = system/global).
- ``chat``      → **global** (resident_id None); visibility is the reader's chat
  cursor, applied at query time via ``max_chat_id``.
- ``utterance`` → the speaker's ``resident_id`` (the speaker remembers their line).

Degrades to a logged no-op (never raises into the tick) when the extension is
unavailable or the embed server is unreachable.
"""

from __future__ import annotations

import logging
from typing import Any

from . import embeddings, vector_index
from .db import get_connection

logger = logging.getLogger(__name__)

# Log an outage/unavailable line at most once per process so a down embed server
# doesn't spam every tick.
_degrade_logged = False

DEFAULT_LIMIT = 500


def _reset_degrade_log() -> None:
    """Test hook — re-arm the once-per-process degrade log."""
    global _degrade_logged
    _degrade_logged = False


def _log_degrade(msg: str) -> None:
    global _degrade_logged
    if not _degrade_logged:
        logger.warning("memory_index degrade: %s", msg)
        _degrade_logged = True


def render_indexable(row: dict, kind: str) -> str:
    """Render a source row to the short line shape used by ``gather_memories``."""
    tick = row.get("tick", "?")
    if kind == "event":
        action = row.get("action") or row.get("kind") or "did something"
        payload = row.get("payload")
        detail = ""
        if isinstance(payload, dict):
            detail = payload.get("summary") or payload.get("text") or ""
        return f"[tick {tick}] you {action}" + (f": {detail}" if detail else "")
    if kind == "chat":
        author = row.get("author_resident_id") or "someone"
        return f"[tick {tick}] chat from {author}: {row.get('body', '')}"
    if kind == "utterance":
        speaker = row.get("speaker_resident_id") or "someone"
        return f"[tick {tick}] call line from {speaker}: {row.get('body', '')}"
    raise ValueError(f"unknown indexable kind: {kind!r}")


_TABLE_FOR_KIND = {"event": "events", "chat": "chat", "utterance": "utterances"}


def fetch_and_render(kind: str, ref_id: int) -> str | None:
    """Fetch a source row by ``(kind, ref_id)`` and render its indexable line.

    Returns None if the row is gone or the kind has no source table (e.g.
    ``lore``, which has no row store until D2). Used by retrieval to map a KNN
    hit back to the exact line a resident would read.
    """
    table = _TABLE_FOR_KIND.get(kind)
    if table is None:
        return None
    conn = get_connection()
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (ref_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    if kind == "event" and d.get("payload"):
        import json

        try:
            d["payload"] = json.loads(d["payload"])
        except (json.JSONDecodeError, TypeError):
            d["payload"] = None
    return render_indexable(d, kind)


# (kind, source table, payload-decode?, how to derive the stored resident_id)
_SOURCES: list[tuple[str, str]] = [
    ("event", "events"),
    ("chat", "chat"),
    ("utterance", "utterances"),
]


def _resident_for(kind: str, row: dict) -> Any:
    if kind == "event":
        return row.get("resident_id")
    if kind == "chat":
        return None  # global; reader's cursor scopes visibility
    if kind == "utterance":
        return row.get("speaker_resident_id")
    return None


def _unindexed_rows(conn, kind: str, table: str, limit: int) -> list[dict]:
    """Source rows (oldest-first) with no ``vec_rowmap`` entry yet."""
    sql = (
        f"SELECT s.* FROM {table} s "
        "LEFT JOIN vec_rowmap m ON m.kind = ? AND m.ref_id = s.id "
        "WHERE m.ref_id IS NULL ORDER BY s.id ASC LIMIT ?"
    )
    rows = conn.execute(sql, (kind, limit)).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if kind == "event" and d.get("payload"):
            import json

            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = None
        out.append(d)
    return out


async def index_pending(*, limit: int = DEFAULT_LIMIT) -> int:
    """Embed + store all un-indexed rows in one batched pass; return the count.

    Idempotent (a row already in ``vec_rowmap`` is skipped). No-op (returns 0,
    logs once) when the vector extension is unavailable or the embed server is
    unreachable — the sim never blocks on the index.
    """
    if not vector_index.is_available():
        _log_degrade("vector extension unavailable")
        return 0

    conn = get_connection()
    pending: list[dict] = []  # each: {kind, ref_id, resident_id, tick, text}
    remaining = limit
    for kind, table in _SOURCES:
        if remaining <= 0:
            break
        for row in _unindexed_rows(conn, kind, table, remaining):
            pending.append(
                {
                    "kind": kind,
                    "ref_id": int(row["id"]),
                    "resident_id": _resident_for(kind, row),
                    "tick": row.get("tick"),
                    "text": render_indexable(row, kind),
                }
            )
            remaining -= 1

    if not pending:
        return 0

    try:
        vectors = await embeddings.embed_texts([p["text"] for p in pending], is_query=False)
    except embeddings.EmbedError as exc:
        _log_degrade(f"embed server unreachable ({exc})")
        return 0

    if len(vectors) != len(pending):
        _log_degrade(
            f"embed returned {len(vectors)} vectors for {len(pending)} rows; skipping"
        )
        return 0

    rows_to_add = [
        {
            "embedding": vec,
            "resident_id": p["resident_id"],
            "kind": p["kind"],
            "ref_id": p["ref_id"],
            "tick": p["tick"],
        }
        for p, vec in zip(pending, vectors)
    ]
    vector_index.add(rows_to_add)
    return len(rows_to_add)
