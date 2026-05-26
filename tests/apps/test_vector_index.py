"""D1.1 — sqlite-vec extension load, migration 2, and the VectorIndex helper.

Uses hand-built float vectors (no embed server). The query vector is the unit
basis vector e0; rows are placed at graded L2 distances so KNN ordering is
deterministic.
"""

from __future__ import annotations

import pytest

from app.apps.blaboratory import chat_store, db, event_store, vector_index

DIM = vector_index.EMBEDDING_DIM


def _vec(idx_to_val: dict[int, float]) -> list[float]:
    """A DIM-length vector, zeros except the given {index: value} entries."""
    v = [0.0] * DIM
    for i, val in idx_to_val.items():
        v[i] = val
    return v


# query vector and three rows at increasing L2 distance from it:
#   A = 1.0*e0  (dist 0.0) · B = 0.5*e0 (dist 0.5) · C = 1.0*e1 (dist ~1.414)
Q = _vec({0: 1.0})
VEC_A = _vec({0: 1.0})
VEC_B = _vec({0: 0.5})
VEC_C = _vec({1: 1.0})

# A,B belong to resident r1; C is global (lore, resident_id=None).
ROWS = [
    {"embedding": VEC_A, "resident_id": "r1", "kind": "event", "ref_id": 1, "tick": 1},
    {"embedding": VEC_B, "resident_id": "r1", "kind": "chat", "ref_id": 5, "tick": 2},
    {"embedding": VEC_C, "resident_id": None, "kind": "lore", "ref_id": 9, "tick": 3},
]


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blaboratory.db")
    db.close_connection()
    yield
    db.close_connection()


# ---- migration + availability ----

def test_fresh_db_migrates_to_v2_with_vec_tables():
    conn = db.get_connection()
    assert vector_index.is_available() is True
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    }
    assert "vec_rowmap" in names
    # the vec0 vtable is queryable
    conn.execute("SELECT count(*) FROM vec_memories")


# ---- KNN ----

def test_add_then_knn_nearest_first():
    db.get_connection()
    vec_ids = vector_index.add(ROWS)
    assert len(vec_ids) == 3
    hits = vector_index.query(Q, k=3)
    assert [(k, rid) for (k, rid, _d) in hits] == [("event", 1), ("chat", 5), ("lore", 9)]
    # distances are non-decreasing (nearest-first)
    dists = [d for (_k, _r, d) in hits]
    assert dists == sorted(dists)
    assert dists[0] == pytest.approx(0.0, abs=1e-5)


# ---- scope filters ----

def test_resident_scope_includes_global_excludes_others():
    db.get_connection()
    vector_index.add(ROWS)
    # r1 sees own rows + global lore
    r1 = {(k, rid) for (k, rid, _d) in vector_index.query(Q, k=3, resident_id="r1")}
    assert r1 == {("event", 1), ("chat", 5), ("lore", 9)}
    # r2 sees only the global lore row, not r1's rows
    r2 = [(k, rid) for (k, rid, _d) in vector_index.query(Q, k=3, resident_id="r2")]
    assert r2 == [("lore", 9)]


def test_kind_filter():
    db.get_connection()
    vector_index.add(ROWS)
    hits = [(k, rid) for (k, rid, _d) in vector_index.query(Q, k=3, kinds=["event"])]
    assert hits == [("event", 1)]
    hits2 = {(k, rid) for (k, rid, _d) in vector_index.query(Q, k=3, kinds=["event", "lore"])}
    assert hits2 == {("event", 1), ("lore", 9)}


def test_max_chat_id_range_excludes_unconsumed_chat():
    db.get_connection()
    vector_index.add(ROWS)
    # chat row B has ref_id=5; cursor at 4 excludes it, non-chat rows unaffected
    hits = [(k, rid) for (k, rid, _d) in vector_index.query(Q, k=3, max_chat_id=4)]
    assert hits == [("event", 1), ("lore", 9)]
    # cursor at 5 lets it back in
    hits2 = {(k, rid) for (k, rid, _d) in vector_index.query(Q, k=3, max_chat_id=5)}
    assert hits2 == {("event", 1), ("chat", 5), ("lore", 9)}


# ---- extension unavailable → graceful degrade ----

def test_extension_unavailable_skips_migration_and_stores_still_work(monkeypatch):
    def _no_vec(conn):
        db.VEC_AVAILABLE = False

    monkeypatch.setattr(db, "_load_vec_extension", _no_vec)
    db.close_connection()

    conn = db.get_connection()
    assert vector_index.is_available() is False
    # user_version still advances; vec tables absent (migration 2 was a no-op)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master").fetchall()
    }
    assert "vec_memories" not in names
    assert "vec_rowmap" not in names

    # add/query degrade to no-ops rather than raising
    assert vector_index.add(ROWS) == []
    assert vector_index.query(Q, k=3) == []

    # existing event/chat stores keep working on the same connection
    eid = event_store.append_event(tick=1, kind="action", resident_id="r1", action="idle")
    assert event_store.events_for_resident("r1")[0]["id"] == eid
    cid = chat_store.append_chat(tick=1, body="hi", author_resident_id="r1")
    assert chat_store.latest_chat_id() == cid
