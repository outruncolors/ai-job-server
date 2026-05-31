"""SP7 — one end-to-end integration test driving the full Prattletale loop.

Exercises the real HTTP surface (TestClient) + the real generator + store
through one complete cycle: **create -> commit a user turn -> model turn ->
induce an error -> retry -> success**, then asserts the on-disk transcript
shape (turn / item ids, statuses, and that the ``system_error`` turn is replaced
**in place** by the retry, not appended).

The only seam is the LLM: ``execute_chain_job`` is replaced by a faithful stub
whose ``final_output.txt`` is flipped between a valid tagged-line reply and a
garbage (un-parseable) reply via a mutable holder — everything else (router,
generator pipeline, parser, store atomic writes, trace capture) runs for real.
The ``voice`` capability is left off, so the loop stays text-only.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import generator, store
from app.apps.prattletale import router as router_module
from app.chain.models import ChainLLMConfig
from app.main import app

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}

_GOOD = "[narration] She doesn't look up from the menu.\n[say] Where else would I be."
_GARBAGE = "   \n   "  # parses to zero items -> a system_error turn


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def llm_output():
    """Mutable holder for the next chain output. The stub executor reads
    ``holder['raw']`` so a single test can flip good <-> garbage mid-flow."""
    return {"raw": _GOOD}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path, llm_output):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(router_module, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )

    async def fake_chain(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(llm_output["raw"], encoding="utf-8")

    monkeypatch.setattr(generator, "execute_chain_job", fake_chain)


def test_full_loop_create_turn_error_retry(client, llm_output):
    base = "/v1/apps/prattletale"

    # --- create ----------------------------------------------------------
    created = client.post(base + "/conversations", json={
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
        "role_instructions": "Stay in character as Mara.",
        "device_user": {"display_name": "You", "persona": "A regular, tired but curious."},
    })
    assert created.status_code == 201, created.text
    conv_id = created.json()["id"]

    # --- commit a user turn -> a good model turn -------------------------
    llm_output["raw"] = _GOOD
    r = client.post(f"{base}/conversations/{conv_id}/turns", json={
        "items": [{"type": "dialogue", "text": "you actually showed up"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_turn"]["id"] == "t0001"
    assert body["user_turn"]["author"] == "user"
    assert body["model_turn"]["id"] == "t0002"
    assert [i["type"] for i in body["model_turn"]["items"]] == ["narration", "dialogue"]
    assert all(i["status"] == "committed" for i in body["model_turn"]["items"])

    # --- induce an error: a second user turn, this time garbage output ---
    llm_output["raw"] = _GARBAGE
    r = client.post(f"{base}/conversations/{conv_id}/turns", json={
        "items": [{"type": "dialogue", "text": "say something"}],
    })
    assert r.status_code == 200, r.text
    error_model = r.json()["model_turn"]
    assert error_model["id"] == "t0004"  # t0003 = the user turn just posted
    assert [i["type"] for i in error_model["items"]] == ["system_error"]
    assert error_model["items"][0]["status"] == "error"

    # --- retry the error turn (output back to good) -> replaced in place -
    llm_output["raw"] = _GOOD
    r = client.post(f"{base}/conversations/{conv_id}/turns/t0004/retry")
    assert r.status_code == 200, r.text
    retried = r.json()
    assert retried["id"] == "t0004"  # same turn id / position, not a new turn
    assert [i["type"] for i in retried["items"]] == ["narration", "dialogue"]
    assert all(i["status"] == "committed" for i in retried["items"])

    # --- assert the on-disk transcript shape -----------------------------
    conv_dir = store.CONVERSATIONS_DIR / conv_id
    transcript = json.loads((conv_dir / "transcript.json").read_text(encoding="utf-8"))

    # exactly four turns, monotonic, alternating user/model, no extra appended
    assert [t["id"] for t in transcript["turns"]] == ["t0001", "t0002", "t0003", "t0004"]
    assert [t["author"] for t in transcript["turns"]] == ["user", "model", "user", "model"]
    assert transcript["next_turn_seq"] == 5

    # the system_error turn was replaced in place: t0004 is now committed text
    t0004 = transcript["turns"][-1]
    assert [i["type"] for i in t0004["items"]] == ["narration", "dialogue"]
    assert all(i["status"] == "committed" for i in t0004["items"])
    assert "system_error" not in {i["type"] for i in t0004["items"]}
    # item ids carry the turn id
    assert [i["id"] for i in t0004["items"]] == ["t0004-i01", "t0004-i02"]

    # the successful retry overwrote the error trace for t0004
    trace = json.loads((conv_dir / "traces" / "t0004.json").read_text(encoding="utf-8"))
    assert trace["error"] is None
    assert trace["raw_final_output"] == _GOOD
    assert len(trace["parsed_items"]) == 2

    # GET reflects the same on-disk state end-to-end
    got = client.get(f"{base}/conversations/{conv_id}").json()
    assert [t["id"] for t in got["transcript"]["turns"]] == ["t0001", "t0002", "t0003", "t0004"]
