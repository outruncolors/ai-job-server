from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.apps.blaboratory import residents_store, rooms
from app.chain.llm_client import StreamChunk

BASE = "/v1/apps/blaboratory"

IDEATE_PROSE = "A vivid character: Edna Marsh, retired astronomer."
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
    "personality": {"traits": ["grumpy"], "quirks": ["hoards teacups"], "speech_style": "dry"},
    "backstory": "Mapped faint stars for forty years.",
}
VALID_JSON = json.dumps(VALID_RESIDENT)


@pytest.fixture(autouse=True)
def tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(residents_store, "RESIDENTS_DIR", tmp_path / "residents")
    monkeypatch.setattr(rooms, "OCCUPANCY_PATH", tmp_path / "occupancy.json")


@pytest.fixture(autouse=True)
def default_llm(monkeypatch):
    """Generation reads get_default_as_chain_llm_config(); supply a fake."""
    from app.chain.models import ChainLLMConfig
    import app.apps.blaboratory.generator as gen
    monkeypatch.setattr(
        gen, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://test/v1", model="test-model"),
    )


def _patch_llm(monkeypatch, scripted: list[str]) -> None:
    state = {"n": 0}

    async def fake_chat_stream(self, messages, llm_config, tools=None):
        i = state["n"]
        state["n"] += 1
        yield StreamChunk(content=scripted[min(i, len(scripted) - 1)])

    monkeypatch.setattr(
        "app.chain.llm_client.OpenAICompatibleLLMClient.chat_stream",
        fake_chat_stream,
    )


@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app)


def test_rooms_list_shape_all_empty(client):
    r = client.get(f"{BASE}/rooms")
    assert r.status_code == 200
    rooms_list = r.json()["rooms"]
    assert len(rooms_list) == 16
    assert rooms_list[0] == {"room_id": 1, "occupant": None}
    assert [room["room_id"] for room in rooms_list] == list(range(1, 17))


def test_create_resident_201_persisted_and_occupied(client, monkeypatch):
    _patch_llm(monkeypatch, [IDEATE_PROSE, VALID_JSON])

    r = client.post(
        f"{BASE}/rooms/1/residents",
        json={"mode": "free_text", "free_text": "a grumpy retired astronomer"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["room_id"] == 1
    assert body["job_id"]
    rid = body["resident"]["id"]
    assert body["resident"]["name"] == "Edna Marsh"

    # Persisted + reflected in rooms list.
    assert client.get(f"{BASE}/residents/{rid}").json()["name"] == "Edna Marsh"
    occupant = next(rm["occupant"] for rm in client.get(f"{BASE}/rooms").json()["rooms"] if rm["room_id"] == 1)
    assert occupant == {"id": rid, "name": "Edna Marsh", "occupation": "retired astronomer", "age": 71}


def test_create_on_occupied_room_409(client, monkeypatch):
    _patch_llm(monkeypatch, [IDEATE_PROSE, VALID_JSON])
    rooms.set_occupant(2, "already-here")

    r = client.post(
        f"{BASE}/rooms/2/residents",
        json={"mode": "free_text", "free_text": "anything"},
    )
    assert r.status_code == 409


def test_free_text_mode_requires_free_text_422(client):
    r = client.post(f"{BASE}/rooms/3/residents", json={"mode": "free_text"})
    assert r.status_code == 422


def test_bad_mode_422(client):
    r = client.post(f"{BASE}/rooms/3/residents", json={"mode": "bogus"})
    assert r.status_code == 422


def test_out_of_range_room_422(client):
    r = client.post(f"{BASE}/rooms/99/residents", json={"mode": "free_text", "free_text": "x"})
    assert r.status_code == 422


def test_generation_failure_502(client, monkeypatch):
    _patch_llm(monkeypatch, [IDEATE_PROSE, "not json"])  # assemble never parses

    r = client.post(
        f"{BASE}/rooms/4/residents",
        json={"mode": "free_text", "free_text": "x"},
    )
    assert r.status_code == 502
    assert rooms.is_empty(4)


def test_get_missing_resident_404(client):
    assert client.get(f"{BASE}/residents/nope").status_code == 404
