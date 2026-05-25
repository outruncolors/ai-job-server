from __future__ import annotations

import json

import pytest

from app.apps.blaboratory import generator, residents_store, rooms
from app.chain.llm_client import StreamChunk
from app.chain.models import ChainLLMConfig

LLM = ChainLLMConfig(api_base="http://test/v1", model="test-model")

IDEATE_PROSE = (
    "Edna Marsh is a 71-year-old retired astronomer, slight and grey-eyed, with "
    "silver hair in a tight bun and wire-rim spectacles. She is grumpy, meticulous, "
    "hoards teacups, and speaks in a clipped, dry manner."
)

VALID_RESIDENT = {
    "name": "Edna Marsh",
    "age": 71,
    "sex": "female",
    "height": "5'4\"",
    "build": "slight",
    "hair_color": "silver",
    "hair_style": "tight bun",
    "eye_color": "grey",
    "skin_tone": "fair",
    "distinguishing_features": ["wire-rim spectacles"],
    "occupation": "retired astronomer",
    "personality": {
        "traits": ["grumpy", "meticulous"],
        "quirks": ["hoards teacups"],
        "speech_style": "clipped and dry",
    },
    "backstory": "Mapped faint stars for forty years.",
}

VALID_JSON = json.dumps(VALID_RESIDENT)
FENCED_JSON = f"```json\n{VALID_JSON}\n```"


@pytest.fixture(autouse=True)
def tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(residents_store, "RESIDENTS_DIR", tmp_path / "residents")
    monkeypatch.setattr(rooms, "OCCUPANCY_PATH", tmp_path / "occupancy.json")


def _patch_llm(monkeypatch, scripted: list[str]) -> dict:
    """Patch chat_stream to yield one scripted response per call (last repeats)."""
    state = {"n": 0}

    async def fake_chat_stream(self, messages, llm_config, tools=None):
        i = state["n"]
        state["n"] += 1
        yield StreamChunk(content=scripted[min(i, len(scripted) - 1)])

    monkeypatch.setattr(
        "app.chain.llm_client.OpenAICompatibleLLMClient.chat_stream",
        fake_chat_stream,
    )
    return state


async def test_free_text_generation_persists_and_occupies(monkeypatch):
    _patch_llm(monkeypatch, [IDEATE_PROSE, VALID_JSON])

    resident, job_id = await generator.run_generation(
        room_id=1, mode="free_text", free_text="a grumpy retired astronomer",
        llm=LLM,
    )

    assert job_id
    assert resident["name"] == "Edna Marsh"
    assert resident["id"]
    assert resident["schema_version"] == 1
    # Persisted to the store and placed in the room (resident first, then occupancy).
    assert residents_store.get_resident(resident["id"])["name"] == "Edna Marsh"
    assert rooms.get_room(1) == resident["id"]


async def test_parse_strips_code_fences(monkeypatch):
    _patch_llm(monkeypatch, [IDEATE_PROSE, FENCED_JSON])

    resident, _ = await generator.run_generation(
        room_id=2, mode="free_text", free_text="x", llm=LLM,
    )
    assert resident["occupation"] == "retired astronomer"
    assert rooms.get_room(2) == resident["id"]


async def test_retry_after_invalid_then_valid(monkeypatch):
    # call 0: ideate prose, call 1: garbage (assemble), call 2: valid JSON (retry assemble-only)
    _patch_llm(monkeypatch, [IDEATE_PROSE, "not json at all", VALID_JSON])

    resident, _ = await generator.run_generation(
        room_id=3, mode="free_text", free_text="x", llm=LLM,
    )
    assert resident["name"] == "Edna Marsh"
    assert rooms.get_room(3) == resident["id"]


async def test_persistent_parse_failure_raises_and_marks_error(monkeypatch):
    from app import jobs as jobs_module

    _patch_llm(monkeypatch, [IDEATE_PROSE, "garbage"])  # every assemble fails

    with pytest.raises(generator.GenerationError):
        await generator.run_generation(room_id=4, mode="free_text", free_text="x", llm=LLM)

    # Room left empty; the underlying job marked error.
    assert rooms.is_empty(4)
    errored = [j for j in jobs_module.list_jobs() if j["status"] == "error"]
    assert errored and errored[0]["job_type"] == generator.JOB_TYPE


async def test_guided_fields_win_over_model(monkeypatch):
    _patch_llm(monkeypatch, [IDEATE_PROSE, VALID_JSON])

    resident, _ = await generator.run_generation(
        room_id=5,
        mode="guided",
        fields={"name": "Bartholomew Quill", "occupation": "clockmaker"},
        llm=LLM,
    )
    # User-supplied guided fields override the model's output.
    assert resident["name"] == "Bartholomew Quill"
    assert resident["occupation"] == "clockmaker"
    # Model-only fields survive.
    assert resident["age"] == 71


async def test_missing_default_llm_raises_generation_error(monkeypatch):
    _patch_llm(monkeypatch, [IDEATE_PROSE, VALID_JSON])

    def _no_default():
        raise RuntimeError("No default LLM preset configured")

    monkeypatch.setattr(generator, "get_default_as_chain_llm_config", _no_default)

    with pytest.raises(generator.GenerationError):
        await generator.run_generation(room_id=7, mode="free_text", free_text="x")  # no llm passed
    assert rooms.is_empty(7)


async def test_occupied_room_rejected_before_generation(monkeypatch):
    state = _patch_llm(monkeypatch, [IDEATE_PROSE, VALID_JSON])
    rooms.set_occupant(6, "someone-else")

    with pytest.raises(generator.GenerationError):
        await generator.run_generation(room_id=6, mode="free_text", free_text="x", llm=LLM)

    assert state["n"] == 0  # no LLM calls — guarded before generation
    assert rooms.get_room(6) == "someone-else"
