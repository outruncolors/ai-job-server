from __future__ import annotations

import pytest

from app.apps.blaboratory import chat_store, cursor_store, db, event_store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point the SQLite db at a fresh tmp file per test and reset the cached conn."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blaboratory.db")
    db.close_connection()
    yield
    db.close_connection()


# ---- migrations ----

def test_fresh_db_migrates_to_latest():
    conn = db.get_connection()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == len(db.MIGRATIONS)
    # tables exist
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"events", "chat", "utterances", "calls", "consumption_cursors"} <= names


def test_migrate_is_idempotent():
    db.get_connection()
    first = db.migrate()
    second = db.migrate()
    assert first == second == len(db.MIGRATIONS)


# ---- events ----

def test_event_append_and_query_roundtrip():
    e1 = event_store.append_event(
        tick=1, kind="action", resident_id="r1", room_id=3, action="idle", payload={"foo": "bar"}
    )
    e2 = event_store.append_event(tick=2, kind="action", resident_id="r1", room_id=3, action="sleep")
    assert e2 > e1

    rows = event_store.events_for_resident("r1")
    assert [r["id"] for r in rows] == [e2, e1]  # newest-first
    assert rows[1]["payload"] == {"foo": "bar"}  # JSON round-trips
    assert rows[0]["payload"] is None

    assert event_store.max_tick() == 2
    assert event_store.latest_event_for_room(3)["id"] == e2
    assert event_store.latest_event_for_room(3, until_tick=1)["id"] == e1
    assert [r["id"] for r in event_store.events_at_tick(1)] == [e1]


def test_events_for_resident_until_tick_truncates():
    event_store.append_event(tick=1, kind="action", resident_id="r1")
    event_store.append_event(tick=5, kind="action", resident_id="r1")
    rows = event_store.events_for_resident("r1", until_tick=3)
    assert len(rows) == 1
    assert rows[0]["tick"] == 1


# ---- chat ----

def test_chat_append_and_cursor_ranges():
    c1 = chat_store.append_chat(tick=1, body="hello", author_resident_id="r1")
    c2 = chat_store.append_chat(tick=1, body="world", author_resident_id="r2")
    assert chat_store.latest_chat_id() == c2

    unconsumed = chat_store.chat_after(c1)
    assert [c["id"] for c in unconsumed] == [c2]

    consumed = chat_store.chat_upto(c2)
    assert [c["id"] for c in consumed] == [c2, c1]  # newest-first


def test_chat_paging_helpers():
    ids = [chat_store.append_chat(tick=i, body=f"m{i}", author_resident_id="r1")
           for i in range(1, 6)]  # ids 1..5, ticks 1..5

    # latest page is oldest-first and bounded
    assert [m["body"] for m in chat_store.chat_latest(limit=3)] == ["m3", "m4", "m5"]

    # older / newer pages around the middle (oldest-first)
    assert [m["id"] for m in chat_store.chat_before(ids[2], limit=10)] == [ids[0], ids[1]]
    assert [m["id"] for m in chat_store.chat_newer(ids[2], limit=10)] == [ids[3], ids[4]]

    # until_tick scopes every helper to the playhead
    assert [m["body"] for m in chat_store.chat_latest(until_tick=2)] == ["m1", "m2"]
    assert chat_store.chat_newer(0, until_tick=3, limit=10)[-1]["tick"] == 3

    assert chat_store.get_chat(ids[1])["body"] == "m2"
    assert chat_store.get_chat(9999) is None


# ---- cursors ----

def test_cursor_get_set_roundtrip():
    assert cursor_store.get_cursor("r1", "chat") == 0
    cursor_store.set_cursor("r1", "chat", 5)
    assert cursor_store.get_cursor("r1", "chat") == 5
    cursor_store.set_cursor("r1", "chat", 9)  # upsert
    assert cursor_store.get_cursor("r1", "chat") == 9
    assert cursor_store.get_cursor("r1", "news") == 0  # independent channel
