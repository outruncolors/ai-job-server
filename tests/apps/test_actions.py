from __future__ import annotations

import pytest

from app.apps.blaboratory import chat_store, cursor_store, db, rooms
from app.apps.blaboratory.actions import breakpoint_clause, get_action, list_actions
from app.apps.blaboratory.actions import sleep as sleep_action


@pytest.fixture(autouse=True)
def tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blaboratory.db")
    monkeypatch.setattr(rooms, "OCCUPANCY_PATH", tmp_path / "occupancy.json")
    db.close_connection()
    yield
    db.close_connection()


def _resident(rid="r1"):
    return {"id": rid, "name": "Edna"}


def test_registry_has_first_action_set():
    names = {a.name for a in list_actions()}
    assert names == {"use_computer", "use_televisor", "use_speakerphone", "sleep", "idle"}


async def test_idle_emits_room_and_summary():
    rooms.set_occupant(3, "r1")
    result = await get_action("idle").run(_resident(), 1, "", {}, deps=None)
    assert result["action"] == "idle"
    assert result["room_id"] == 3
    assert "consume" not in result


async def test_use_computer_consumes_chat_and_optionally_posts():
    rooms.set_occupant(2, "r1")
    result = await get_action("use_computer").run(_resident(), 1, "", {"post": "hi all"}, deps=None)
    assert result["consume"] == ["chat"]
    assert result["chat_post"] == "hi all"
    assert result["room_id"] == 2


async def test_use_televisor_consumes_news():
    result = await get_action("use_televisor").run(_resident(), 1, "", {}, deps=None)
    assert result["consume"] == ["news"]


def test_breakpoint_clause_escalates_with_count():
    sleep = sleep_action.action
    assert breakpoint_clause(sleep, 1) == ""  # below first threshold
    assert "wake soon" in breakpoint_clause(sleep, 3)
    assert "wake up now" in breakpoint_clause(sleep, 6)
    assert sleep.multi_tick is True
