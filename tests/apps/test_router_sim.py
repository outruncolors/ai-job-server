from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.apps.blaboratory import (
    activity_store,
    context_pipeline,
    db,
    event_store,
    residents_store,
    rooms,
    sim_clock,
    tick_runner,
)
from app.chain.llm_client import StreamChunk
from app.chain.models import ChainLLMConfig

LLM = ChainLLMConfig(api_base="http://test/v1", model="test-model")


@pytest.fixture(autouse=True)
def tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blaboratory.db")
    monkeypatch.setattr(rooms, "OCCUPANCY_PATH", tmp_path / "occupancy.json")
    monkeypatch.setattr(residents_store, "RESIDENTS_DIR", tmp_path / "residents")
    monkeypatch.setattr(activity_store, "ACTIVITIES_PATH", tmp_path / "activities.json")
    monkeypatch.setattr(context_pipeline, "LORE_PATH", tmp_path / "lore.json")
    db.close_connection()
    yield
    db.close_connection()


@pytest.fixture()
def client():
    from app.main import app

    return TestClient(app)


def _char_fields(name: str) -> dict:
    return {
        "name": name, "age": 40, "sex": "female", "height": "5'6\"", "build": "average",
        "hair_color": "brown", "hair_style": "short", "eye_color": "hazel", "skin_tone": "tan",
        "distinguishing_features": [], "occupation": "tinkerer",
        "personality": {"traits": ["curious"], "quirks": [], "speech_style": "warm"},
        "backstory": "Likes gadgets.",
    }


def _seed(name: str, room: int) -> str:
    r = residents_store.create_resident(_char_fields(name))
    rooms.set_occupant(room, r["id"])
    return r["id"]


def test_latest_tick_and_events_truncation(client):
    a = _seed("Ada", 1)
    event_store.append_event(tick=1, kind="action", resident_id=a, room_id=1, action="idle")
    event_store.append_event(tick=5, kind="action", resident_id=a, room_id=1, action="sleep")

    assert client.get("/v1/apps/blaboratory/ticks/latest").json()["tick"] == 5

    r = client.get(f"/v1/apps/blaboratory/residents/{a}/events", params={"until_tick": 3})
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["tick"] == 1  # nothing past the playhead

    # newest-first when not truncated
    allr = client.get(f"/v1/apps/blaboratory/residents/{a}/events").json()["events"]
    assert [e["tick"] for e in allr] == [5, 1]


def test_rooms_at_tick_action_word(client):
    a = _seed("Ada", 1)
    event_store.append_event(tick=2, kind="action", resident_id=a, room_id=1, action="use_computer")

    data = client.get("/v1/apps/blaboratory/ticks/2/rooms").json()
    by_room = {r["room_id"]: r for r in data["rooms"]}
    assert by_room[1]["occupant"]["name"] == "Ada"
    assert by_room[1]["action_word"] == "computer"
    assert by_room[2]["occupant"] is None and by_room[2]["action_word"] is None


def test_context_endpoint(client):
    a = _seed("Ada", 1)
    r = client.get(f"/v1/apps/blaboratory/residents/{a}/context")
    body = r.json()
    assert "[Overview]" in body["context"] and "Ada" in body["context"]


def test_utterances_empty_and_clock_default(client):
    _seed("Ada", 1)
    assert client.get("/v1/apps/blaboratory/rooms/1/utterances").json()["utterances"] == []
    assert client.get("/v1/apps/blaboratory/clock").json()["running"] is False


def test_fire_route_delegates(client, monkeypatch):
    a = _seed("Ada", 1)
    event_store.append_event(tick=4, kind="action", resident_id=a, action="idle")

    async def fake_fire(tick=None):
        return "job-xyz"

    monkeypatch.setattr(sim_clock, "fire_tick", fake_fire)
    r = client.post("/v1/apps/blaboratory/ticks/fire").json()
    assert r == {"tick": 5, "job_id": "job-xyz"}  # next_tick = max(4)+1


def test_clock_control_wiring(client, monkeypatch):
    fake = SimpleNamespace(running=False)

    async def _start():
        fake.running = True

    async def _stop():
        fake.running = False

    fake.start, fake.stop = _start, _stop
    monkeypatch.setattr(sim_clock, "get_sim_clock", lambda: fake)

    assert client.post("/v1/apps/blaboratory/clock/start").json()["running"] is True
    assert client.post("/v1/apps/blaboratory/clock/stop").json()["running"] is False


async def test_fire_tick_end_to_end(monkeypatch):
    """fire_tick → LOW job → run_tick writes events and advances the counter."""
    import app.job_queue as jq

    a = _seed("Ada", 1)

    async def fake_chat_stream(self, messages, llm_config, tools=None):
        yield StreamChunk(content='{"action": "idle"}')

    monkeypatch.setattr(
        "app.chain.llm_client.OpenAICompatibleLLMClient.chat_stream", fake_chat_stream
    )
    monkeypatch.setattr(tick_runner, "get_default_as_chain_llm_config", lambda: LLM)

    jq.reset_job_queue()
    queue = jq.get_job_queue()
    await queue.start()
    try:
        await sim_clock.fire_tick(1)
        for _ in range(300):
            if queue.depth() == 0 and queue.current_job_id is None and event_store.max_tick() >= 1:
                break
            await asyncio.sleep(0.01)
        assert event_store.max_tick() == 1
        assert len(event_store.events_for_resident(a)) == 1
    finally:
        await queue.stop()
        jq.reset_job_queue()
