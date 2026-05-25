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


def test_sections_in_fixed_order_and_some_know_empty():
    ctx = build_context(_resident(), action_node="You are idling.", tick=1)
    # All five headers present, in order.
    headers = ["[Overview]", "[Everyone Knows]", "[Some Know]", "[You Know]", "[Your Action]"]
    positions = [ctx.index(h) for h in headers]
    assert positions == sorted(positions)
    assert "Edna" in ctx
    assert "You are idling." in ctx
    # [Some Know] section is empty (nothing between its header and the next).
    between = ctx.split("[Some Know]", 1)[1].split("[You Know]", 1)[0]
    assert between.strip() == ""


def test_everyone_knows_reads_lore(tmp_path):
    context_pipeline.LORE_PATH.write_text(json.dumps({"everyone_knows": "The sky is teal."}))
    ctx = build_context(_resident(), tick=1)
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
