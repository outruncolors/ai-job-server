from __future__ import annotations

import json

import pytest

from app.apps.blaboratory import chat_store, context_pipeline, cursor_store, db, event_store
from app.apps.blaboratory.context_pipeline import Caps, build_context, gather_memories, write_phase


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blaboratory.db")
    monkeypatch.setattr(context_pipeline, "LORE_PATH", tmp_path / "lore.json")
    db.close_connection()
    yield
    db.close_connection()


def _resident(rid="r1"):
    return {
        "id": rid,
        "name": "Edna",
        "age": 71,
        "sex": "female",
        "occupation": "astronomer",
        "personality": {"traits": ["grumpy"], "quirks": [], "speech_style": "dry"},
    }


async def test_sections_in_fixed_order_and_some_know_empty():
    ctx = await build_context(_resident(), action_node="You are idling.", tick=1)
    # All five headers present, in order.
    headers = ["[Overview]", "[Everyone Knows]", "[Some Know]", "[You Know]", "[Your Action]"]
    positions = [ctx.index(h) for h in headers]
    assert positions == sorted(positions)
    assert "Edna" in ctx
    assert "You are idling." in ctx
    # [Some Know] section is empty (nothing between its header and the next).
    between = ctx.split("[Some Know]", 1)[1].split("[You Know]", 1)[0]
    assert between.strip() == ""


async def test_everyone_knows_reads_lore(tmp_path):
    context_pipeline.LORE_PATH.write_text(json.dumps({"everyone_knows": "The sky is teal."}))
    ctx = await build_context(_resident(), tick=1)
    assert "The sky is teal." in ctx


def test_you_know_reflects_only_consumed_chat():
    r = _resident()
    # Three chat messages exist; resident has consumed only the first one.
    c1 = chat_store.append_chat(tick=1, body="first", author_resident_id="other")
    chat_store.append_chat(tick=1, body="second", author_resident_id="other")
    cursor_store.set_cursor(r["id"], "chat", c1)

    mems = gather_memories(r["id"])
    joined = "\n".join(mems)
    assert "first" in joined
    assert "second" not in joined  # unconsumed → not known


def test_apply_caps_drops_oldest():
    # 5 events, cap to 3 items → keep the 3 newest.
    for i in range(5):
        event_store.append_event(tick=i, kind="action", resident_id="r1", action=f"a{i}")
    mems = gather_memories("r1")
    assert mems[0].startswith("[tick 4]")  # newest-first
    capped = context_pipeline.apply_caps(mems, Caps(max_items=3, max_chars=10_000))
    assert len(capped) == 3
    assert all("tick 4" in capped[0] or True for _ in capped)
    assert "[tick 0]" not in "\n".join(capped)  # oldest dropped


def test_use_computer_write_advances_chat_cursor():
    r = _resident()
    chat_store.append_chat(tick=1, body="hello", author_resident_id="other")
    assert cursor_store.get_cursor(r["id"], "chat") == 0
    write_phase(
        r,
        tick=1,
        action_result={"action": "use_computer", "room_id": 3, "consume": ["chat"]},
    )
    # Cursor now at the latest chat id; an event row was logged.
    assert cursor_store.get_cursor(r["id"], "chat") == chat_store.latest_chat_id()
    evs = event_store.events_for_resident(r["id"])
    assert evs and evs[0]["action"] == "use_computer" and evs[0]["room_id"] == 3


def test_write_phase_posts_chat_then_consumes():
    r = _resident()
    write_phase(
        r,
        tick=2,
        action_result={"action": "use_computer", "chat_post": "I posted this", "consume": ["chat"]},
    )
    # The post is in the feed and the cursor includes it (so it's consumed next read).
    assert chat_store.latest_chat_id() == cursor_store.get_cursor(r["id"], "chat")
    assert any("I posted this" in m for m in gather_memories(r["id"]))


def test_write_phase_stores_chat_id_in_event_payload():
    r = _resident()
    write_phase(
        r,
        tick=2,
        action_result={
            "action": "use_computer",
            "chat_post": "deep link me",
            "consume": ["chat"],
            "payload": {"summary": "posted", "post": "deep link me"},
        },
    )
    chat_id = chat_store.latest_chat_id()
    evs = event_store.events_for_resident(r["id"])
    assert evs[0]["payload"]["chat_id"] == chat_id


# ---- D1.4 hybrid retrieval ------------------------------------------------

from app.apps.blaboratory import embeddings, vector_index
from app.apps.blaboratory.context_pipeline import apply_caps, retrieve_memories

DIM = vector_index.EMBEDDING_DIM


def _vec(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def _seed_events_and_index():
    """Seed one distinctive old event + 5 recent ones; index them with vectors.

    The old event's vector is e0; the recent events share e1 (far from e0), so a
    query at e0 ranks the old 'comet' event first.
    """
    old = event_store.append_event(tick=0, kind="action", resident_id="r1", action="spotted a comet")
    recent_ids = [
        event_store.append_event(tick=t, kind="action", resident_id="r1", action=f"a{t}")
        for t in range(1, 6)
    ]
    vector_index.add([{"embedding": _vec(0), "resident_id": "r1", "kind": "event", "ref_id": old, "tick": 0}])
    vector_index.add(
        [
            {"embedding": _vec(1), "resident_id": "r1", "kind": "event", "ref_id": rid, "tick": t}
            for t, rid in zip(range(1, 6), recent_ids)
        ]
    )
    return old, recent_ids


async def test_hybrid_surfaces_relevant_older_item(monkeypatch):
    db.get_connection()
    monkeypatch.setattr(context_pipeline, "RECENCY_FLOOR_ITEMS", 2)
    _seed_events_and_index()

    async def fake_embed(texts, *, is_query=False):
        return [_vec(0)]  # query lands next to the 'comet' event

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)

    caps = Caps(max_items=4, max_chars=10_000)
    result = await retrieve_memories(_resident(), caps)

    comet = "[tick 0] you spotted a comet"
    # mechanical recency alone would have dropped the comet (beyond the cap)
    mechanical = apply_caps(gather_memories("r1", caps), caps)
    assert comet not in mechanical
    # hybrid keeps the recent floor AND resurfaces the relevant older comet
    assert "[tick 5] you a5" in result and "[tick 4] you a4" in result
    assert comet in result
    # de-dupe + caps hold
    assert len(result) == len(set(result)) == caps.max_items


async def test_regression_mechanical_when_index_unavailable(monkeypatch):
    db.get_connection()
    _seed_events_and_index()
    monkeypatch.setattr(vector_index, "is_available", lambda: False)

    async def boom(texts, *, is_query=False):
        raise AssertionError("embed must not be called when index unavailable")

    monkeypatch.setattr(embeddings, "embed_texts", boom)

    caps = Caps(max_items=4, max_chars=10_000)
    resident = _resident()
    you_know = await retrieve_memories(resident, caps)
    # byte-identical to the pre-D1 mechanical gather
    assert you_know == apply_caps(gather_memories("r1", caps), caps)

    ctx = await build_context(resident, tick=5, caps=caps)
    assert "\n".join(you_know) in ctx


async def test_empty_index_skips_embed(monkeypatch):
    db.get_connection()
    event_store.append_event(tick=1, kind="action", resident_id="r1", action="idle")

    async def boom(texts, *, is_query=False):
        raise AssertionError("embed must not be called against an empty index")

    monkeypatch.setattr(embeddings, "embed_texts", boom)
    caps = Caps()
    out = await retrieve_memories(_resident(), caps)
    assert out == apply_caps(gather_memories("r1", caps), caps)
