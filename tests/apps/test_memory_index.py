"""D1.3 — index_pending batch backfill (patched embed, no live server)."""

from __future__ import annotations

import pytest

from app.apps.blaboratory import (
    chat_store,
    db,
    embeddings,
    event_store,
    memory_index,
    utterance_store,
    vector_index,
)

DIM = vector_index.EMBEDDING_DIM


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blaboratory.db")
    db.close_connection()
    memory_index._reset_degrade_log()
    yield
    db.close_connection()


def _patch_embed(monkeypatch, *, fail=False):
    calls = {"n": 0, "texts": []}

    async def fake_embed(texts, *, is_query=False):
        calls["n"] += 1
        calls["texts"].append(list(texts))
        if fail:
            raise embeddings.EmbedError("embed server down")
        return [[float(i)] * DIM for i in range(len(texts))]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    return calls


def _counts():
    conn = db.get_connection()
    vm = conn.execute("SELECT count(*) FROM vec_memories").fetchone()[0]
    rm = conn.execute("SELECT count(*) FROM vec_rowmap").fetchone()[0]
    return vm, rm


# ---- render shape ----

def test_render_indexable_shapes():
    ev = {"tick": 4, "action": "checked the computer", "payload": {"summary": "saw a meme"}}
    assert memory_index.render_indexable(ev, "event") == "[tick 4] you checked the computer: saw a meme"
    ch = {"tick": 2, "author_resident_id": "r2", "body": "hello"}
    assert memory_index.render_indexable(ch, "chat") == "[tick 2] chat from r2: hello"
    ut = {"tick": 7, "speaker_resident_id": "r1", "body": "hi there"}
    assert memory_index.render_indexable(ut, "utterance") == "[tick 7] call line from r1: hi there"


# ---- indexing ----

async def test_index_pending_indexes_each_once(monkeypatch):
    db.get_connection()
    e1 = event_store.append_event(tick=1, kind="action", resident_id="r1", action="idle",
                                  payload={"summary": "stood around"})
    c1 = chat_store.append_chat(tick=1, body="hello", author_resident_id="r1")
    c2 = chat_store.append_chat(tick=2, body="world", author_resident_id="r2")

    calls = _patch_embed(monkeypatch)
    n = await memory_index.index_pending()
    assert n == 3
    assert _counts() == (3, 3)
    assert calls["n"] == 1  # single batched embed call

    # rowmap maps the right (kind, ref_id) pairs
    conn = db.get_connection()
    pairs = {(r["kind"], r["ref_id"]) for r in conn.execute("SELECT kind, ref_id FROM vec_rowmap")}
    assert pairs == {("event", e1), ("chat", c1), ("chat", c2)}

    # chat rows are global (resident_id stored as the empty-string sentinel);
    # the event row carries its resident
    res_by_kind = {
        (r["kind"], r["ref_id"]): r["resident_id"]
        for r in conn.execute("SELECT kind, ref_id, resident_id FROM vec_memories")
    }
    assert res_by_kind[("chat", c1)] == ""
    assert res_by_kind[("event", e1)] == "r1"


async def test_second_call_is_noop(monkeypatch):
    db.get_connection()
    event_store.append_event(tick=1, kind="action", resident_id="r1", action="idle")
    calls = _patch_embed(monkeypatch)

    assert await memory_index.index_pending() == 1
    assert await memory_index.index_pending() == 0  # nothing new
    assert _counts() == (1, 1)
    assert calls["n"] == 1  # second call doesn't embed


async def test_incremental_picks_up_new_rows(monkeypatch):
    db.get_connection()
    event_store.append_event(tick=1, kind="action", resident_id="r1", action="idle")
    _patch_embed(monkeypatch)
    assert await memory_index.index_pending() == 1

    # a new utterance authored later gets indexed on the next pass
    utterance_store.append_utterance(call_id=1, tick=2, speaker_resident_id="r1",
                                     room_id=3, body="hi", seq=0)
    assert await memory_index.index_pending() == 1
    assert _counts() == (2, 2)


# ---- degradation ----

async def test_embed_outage_leaves_rows_unindexed_without_raising(monkeypatch):
    db.get_connection()
    event_store.append_event(tick=1, kind="action", resident_id="r1", action="idle")
    _patch_embed(monkeypatch, fail=True)

    n = await memory_index.index_pending()  # must not raise
    assert n == 0
    assert _counts() == (0, 0)


async def test_extension_unavailable_is_noop(monkeypatch):
    def _no_vec(conn):
        db.VEC_AVAILABLE = False

    monkeypatch.setattr(db, "_load_vec_extension", _no_vec)
    db.close_connection()
    db.get_connection()
    event_store.append_event(tick=1, kind="action", resident_id="r1", action="idle")
    _patch_embed(monkeypatch)

    assert await memory_index.index_pending() == 0
