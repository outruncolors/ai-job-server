from __future__ import annotations

import pytest

from app.apps.blaboratory import (
    activity_store,
    context_pipeline,
    db,
    event_store,
    residents_store,
    rooms,
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


def _char_fields(name: str) -> dict:
    return {
        "name": name, "age": 40, "sex": "female", "height": "5'6\"", "build": "average",
        "hair_color": "brown", "hair_style": "short", "eye_color": "hazel", "skin_tone": "tan",
        "distinguishing_features": [], "occupation": "tinkerer",
        "personality": {"traits": ["curious"], "quirks": [], "speech_style": "warm"},
        "backstory": "Likes gadgets.",
    }


def _patch_llm(monkeypatch, response: str):
    async def fake_chat_stream(self, messages, llm_config, tools=None):
        yield StreamChunk(content=response)

    monkeypatch.setattr(
        "app.chain.llm_client.OpenAICompatibleLLMClient.chat_stream", fake_chat_stream
    )


def _seed(name: str, room: int) -> str:
    r = residents_store.create_resident(_char_fields(name))
    rooms.set_occupant(room, r["id"])
    return r["id"]


async def test_run_tick_all_occupants_act_and_tick_advances(monkeypatch):
    _patch_llm(monkeypatch, '{"action": "idle", "args": {}}')
    a = _seed("Ada", 1)
    b = _seed("Bee", 2)

    summary = await tick_runner.run_tick(1, llm=LLM)

    assert summary["tick"] == 1
    assert {x["resident_id"] for x in summary["acted"]} == {a, b}
    # one event each, tick recorded
    assert len(event_store.events_for_resident(a)) == 1
    assert len(event_store.events_for_resident(b)) == 1
    assert event_store.max_tick() == 1


async def test_unknown_action_falls_back_to_idle(monkeypatch):
    _patch_llm(monkeypatch, "this is not json")
    a = _seed("Ada", 1)
    await tick_runner.run_tick(1, llm=LLM)
    ev = event_store.events_for_resident(a)[0]
    assert ev["action"] == "idle"


async def test_sleep_starts_and_continues(monkeypatch):
    a = _seed("Ada", 1)

    _patch_llm(monkeypatch, '{"action": "sleep"}')
    await tick_runner.run_tick(1, llm=LLM)
    act = activity_store.get_activity(a)
    assert act == {"action": "sleep", "count": 1}

    _patch_llm(monkeypatch, '{"action": "continue"}')
    await tick_runner.run_tick(2, llm=LLM)
    act = activity_store.get_activity(a)
    assert act == {"action": "sleep", "count": 2}
    # both ticks logged a sleep event
    actions = [e["action"] for e in event_store.events_for_resident(a)]
    assert actions == ["sleep", "sleep"]


def test_decision_node_lists_options_and_breakpoint():
    # No activity → no continue option, no breakpoint.
    node = tick_runner.decision_node(None)
    assert '"use_computer"' in node and '"idle"' in node
    assert '"continue"' not in node

    # Ongoing sleep past a breakpoint threshold → clause is composed in.
    node = tick_runner.decision_node({"action": "sleep", "count": 6})
    assert '"continue"' in node
    assert "wake up now" in node


async def test_no_default_llm_skips_cleanly(monkeypatch):
    def _raise():
        raise RuntimeError("no default")

    monkeypatch.setattr(tick_runner, "get_default_as_chain_llm_config", _raise)
    _seed("Ada", 1)
    summary = await tick_runner.run_tick(1)  # no llm passed
    assert summary["skipped"] == "no_default_llm"
    assert summary["acted"] == []
