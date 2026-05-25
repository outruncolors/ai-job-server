from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.apps.blaboratory import call_sequence, db, residents_store, rooms, utterance_store
from app.chain.llm_client import StreamChunk
from app.chain.models import ChainLLMConfig

LLM = ChainLLMConfig(api_base="http://test/v1", model="test-model")


@pytest.fixture(autouse=True)
def tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "blaboratory.db")
    monkeypatch.setattr(rooms, "OCCUPANCY_PATH", tmp_path / "occupancy.json")
    monkeypatch.setattr(residents_store, "RESIDENTS_DIR", tmp_path / "residents")
    monkeypatch.setattr(call_sequence.context_pipeline, "LORE_PATH", tmp_path / "lore.json")
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


def _patch_llm(monkeypatch, scripted: list[str]):
    """One scripted response per LLM call (last repeats)."""
    state = {"n": 0}

    async def fake_chat_stream(self, messages, llm_config, tools=None):
        i = state["n"]
        state["n"] += 1
        yield StreamChunk(content=scripted[min(i, len(scripted) - 1)])

    monkeypatch.setattr(
        "app.chain.llm_client.OpenAICompatibleLLMClient.chat_stream", fake_chat_stream
    )
    return state


def _seed_pair():
    caller = residents_store.create_resident(_char_fields("Ada"))
    callee = residents_store.create_resident(_char_fields("Bee"))
    rooms.set_occupant(1, caller["id"])
    rooms.set_occupant(2, callee["id"])
    return caller, callee


async def test_accept_path_writes_call_and_ordered_utterances(monkeypatch):
    # accept, opening topic line, then CONTINUE→reply, then END.
    _patch_llm(monkeypatch, ["ACCEPT", "Hello, lovely day.", "CONTINUE", "Indeed it is!", "END"])
    caller, callee = _seed_pair()
    deps = SimpleNamespace(busy=set(), llm=LLM)

    result = await call_sequence.run_call(caller, callee, tick=1, llm=LLM, deps=deps)

    assert result["accepted"] is True
    assert result["lines"] == 2  # opening + one reply
    # call row exists and is accepted
    convo = utterance_store.utterances_for_call(result["call_id"])
    assert len(convo) == 4  # 2 lines × 2 rooms
    # each room shows both lines, in seq order
    room1 = utterance_store.utterances_for_room(1)
    assert [u["seq"] for u in sorted(room1, key=lambda u: u["seq"])] == [1, 2]
    assert {u["body"] for u in room1} == {"Hello, lovely day.", "Indeed it is!"}
    # callee forfeits its action this tick
    assert callee["id"] in deps.busy


async def test_decline_path_short_call_no_exchange(monkeypatch):
    _patch_llm(monkeypatch, ["DECLINE"])
    caller, callee = _seed_pair()
    deps = SimpleNamespace(busy=set(), llm=LLM)

    result = await call_sequence.run_call(caller, callee, tick=1, llm=LLM, deps=deps)

    assert result["accepted"] is False
    assert result["lines"] == 0
    assert utterance_store.utterances_for_call(result["call_id"]) == []
    # declined → callee keeps its action
    assert callee["id"] not in deps.busy


async def test_segue_re_enters_topic_select(monkeypatch):
    # accept, opening topic, SEGUE→new topic+reply, then END.
    _patch_llm(
        monkeypatch,
        ["ACCEPT", "First topic line.", "SEGUE", "Fresh topic line.", "END"],
    )
    caller, callee = _seed_pair()
    deps = SimpleNamespace(busy=set(), llm=LLM)

    result = await call_sequence.run_call(caller, callee, tick=1, llm=LLM, deps=deps)
    # two topic selections occurred (opening + one segue).
    assert len(result["topics"]) == 2


async def test_tick_runner_routes_speakerphone(monkeypatch, tmp_path):
    """End-to-end: a resident choosing use_speakerphone places a real call."""
    from app.apps.blaboratory import activity_store, tick_runner

    monkeypatch.setattr(activity_store, "ACTIVITIES_PATH", tmp_path / "activities.json")
    caller, callee = _seed_pair()

    # caller (room 1) decides use_speakerphone; the call's turns follow; the
    # callee (room 2) decides idle (it acts unless marked busy first).
    _patch_llm(
        monkeypatch,
        ['{"action": "use_speakerphone"}', "ACCEPT", "Hi there.", "END",
         '{"action": "idle"}'],
    )
    summary = await tick_runner.run_tick(1, llm=LLM)
    actions = {a["action"] for a in summary["acted"]}
    assert "use_speakerphone" in actions
    # a call row was created
    rows = db.get_connection().execute("SELECT COUNT(*) c FROM calls").fetchone()["c"]
    assert rows >= 1
