"""SP7 — Phase 2 (config + dev tools) edge cases + one end-to-end integration.

Drives the real generator pipeline with a faithful fake executor (writes both
``final_output.txt`` and the per-step ``steps/NNN_<id>/`` output dirs, so trace
enrichment is exercised), plus the store ops and HTTP surface. No LLM / network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import wildcards
from app.apps.prattletale import generator, router as router_module, store
from app.chain.models import ChainLLMConfig
from app.main import app
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")
    monkeypatch.setattr(wildcards, "_DIR", tmp_path / "wildcards")
    monkeypatch.setattr(wildcards, "_INDEX_PATH", tmp_path / "wildcards" / "index.json")
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(router_module, "get_character", lambda cid: dict(_CHARACTER))


@pytest.fixture()
def client():
    return TestClient(app)


def _fake_chain(final_output: str):
    async def fake(job_id, job_dir, request, event_bus=None):
        steps_dir = job_dir / "steps"
        for step in request.steps:
            d = steps_dir / f"{step.number:03d}_{step.id}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "prompt.txt").write_text(f"rendered:{step.id}", encoding="utf-8")
            (d / "output.txt").write_text(f"out:{step.id}", encoding="utf-8")
        (job_dir / "final_output.txt").write_text(final_output, encoding="utf-8")
    return fake


def _seed(**config) -> str:
    return store.create_conversation({
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
        "device_user": {"display_name": "You", "persona": "A regular."},
        "config": config or {},
    })["id"]


# --- edge: edit / hide / delete corners -------------------------------------

def test_edit_the_only_item_of_a_turn():
    cid = _seed()
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "old"}], job_id="j")
    updated = store.edit_item(cid, turn["id"], turn["items"][0]["id"], "new")
    assert updated["items"][0]["text"] == "new"
    assert len(store.get_transcript(cid)["turns"]) == 1


def test_edit_a_system_error_turn_item():
    cid = _seed()
    err = store.append_error_turn(cid, "boom", job_id="j")
    item_id = err["items"][0]["id"]
    updated = store.edit_item(cid, err["id"], item_id, "edited error note")
    assert updated["items"][0]["text"] == "edited error note"
    assert updated["items"][0]["type"] == "system_error"


def test_delete_mid_list_turn_keeps_other_ids():
    cid = _seed()
    store.append_user_turn(cid, [{"type": "dialogue", "text": "one"}])
    mid = store.append_model_turn(cid, [{"type": "dialogue", "text": "two"}], job_id="j")
    store.append_user_turn(cid, [{"type": "dialogue", "text": "three"}])
    store.delete_turn(cid, mid["id"])
    assert [t["id"] for t in store.get_transcript(cid)["turns"]] == ["t0001", "t0003"]


def test_hidden_then_shown_round_trip_restores_to_context():
    cid = _seed()
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "tell-me"}], job_id="j")
    item_id = turn["items"][0]["id"]
    conv = store.get_conversation(cid)

    store.set_item_hidden(cid, turn["id"], item_id, True)
    ctx = generator.build_context(conv, dict(_CHARACTER), store.get_transcript(cid))
    assert "tell-me" not in ctx["transcript"]

    store.set_item_hidden(cid, turn["id"], item_id, False)
    ctx = generator.build_context(conv, dict(_CHARACTER), store.get_transcript(cid))
    assert "tell-me" in ctx["transcript"]


def test_fully_hidden_turn_leaves_no_dangling_label():
    cid = _seed()
    store.append_user_turn(cid, [{"type": "dialogue", "text": "visible-user"}])
    hidden_turn = store.append_model_turn(cid, [
        {"type": "dialogue", "text": "secret-a"},
        {"type": "narration", "text": "secret-b"},
    ], job_id="j")
    for it in hidden_turn["items"]:
        store.set_item_hidden(cid, hidden_turn["id"], it["id"], True)

    ctx = generator.build_context(store.get_conversation(cid), dict(_CHARACTER), store.get_transcript(cid))
    # the all-hidden turn produces no line at all — no "[Mara] " with empty body
    assert ctx["transcript"].splitlines() == ['[User] "visible-user"']
    assert "Mara" not in ctx["transcript"]


def test_concurrent_edit_and_posted_turn_both_survive():
    """The store re-reads before writing, so an edit + an append racing on one
    conversation don't clobber each other."""
    cid = _seed()
    t1 = store.append_user_turn(cid, [{"type": "dialogue", "text": "first"}])
    # simulate: read transcript, then a NEW turn lands, then the edit writes back.
    store.append_model_turn(cid, [{"type": "dialogue", "text": "second"}], job_id="j")
    store.edit_item(cid, t1["id"], t1["items"][0]["id"], "first-edited")

    turns = store.get_transcript(cid)["turns"]
    assert [t["id"] for t in turns] == ["t0001", "t0002"]
    assert turns[0]["items"][0]["text"] == "first-edited"
    assert turns[1]["items"][0]["text"] == "second"


# --- edge: settings windows -------------------------------------------------

def test_window_larger_than_turn_count_returns_all(client):
    cid = _seed()
    for n in range(1, 4):
        store.append_user_turn(cid, [{"type": "dialogue", "text": str(n)}])
    client.patch(f"/v1/apps/prattletale/conversations/{cid}", json={"config": {"context_window_turns": 999}})
    ctx = generator.build_context(store.get_conversation(cid), dict(_CHARACTER), store.get_transcript(cid))
    assert ctx["transcript"].splitlines() == ['[User] "1"', '[User] "2"', '[User] "3"']


def test_window_zero_rejected(client):
    cid = _seed()
    assert client.patch(
        f"/v1/apps/prattletale/conversations/{cid}", json={"config": {"context_window_turns": 0}}
    ).status_code == 422


# --- edge: trace read -------------------------------------------------------

def test_trace_read_no_trace_and_missing_conversation(client):
    cid = _seed()
    store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    assert client.get(f"/v1/apps/prattletale/conversations/{cid}/turns/t0001/trace").status_code == 404
    assert client.get("/v1/apps/prattletale/conversations/nope/turns/t0001/trace").status_code == 404


# --- the end-to-end integration ---------------------------------------------

async def test_config_devtools_end_to_end(client, monkeypatch):
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("[say] Where else would I be."))
    cid = _seed(variety_pass_enabled=True)

    # commit a user + model turn through the real pipeline
    user_turn = store.append_user_turn(cid, [{"type": "dialogue", "text": "you showed up"}])
    model_turn, _ = await generator.run_model_turn(cid)
    assert model_turn["author"] == "model"

    # edit the user item
    store.edit_item(cid, user_turn["id"], user_turn["items"][0]["id"], "you actually showed up")
    assert store.get_transcript(cid)["turns"][0]["items"][0]["text"] == "you actually showed up"

    # hide the model item, then run the NEXT turn and assert its trace omits it
    store.set_item_hidden(cid, model_turn["id"], model_turn["items"][0]["id"], True)
    next_turn, _ = await generator.run_model_turn(cid)
    next_trace = store.get_trace(cid, next_turn["id"])
    assert "Where else would I be." not in next_trace["context_input"]["transcript"]
    assert "you actually showed up" in next_trace["context_input"]["transcript"]

    # patch the context window and confirm the slice changed
    r = client.patch(f"/v1/apps/prattletale/conversations/{cid}", json={"config": {"context_window_turns": 1}})
    assert r.status_code == 200
    ctx = generator.build_context(store.get_conversation(cid), dict(_CHARACTER), store.get_transcript(cid))
    assert len(ctx["transcript"].splitlines()) <= 1  # only the most recent visible turn

    # read the enriched trace shape over HTTP (turn -> variety; guard retired)
    trace = client.get(
        f"/v1/apps/prattletale/conversations/{cid}/turns/{next_turn['id']}/trace"
    ).json()
    assert [s["id"] for s in trace["steps"]] == ["turn", "variety"]
    assert trace["steps"][0]["output"] == "out:turn"

    # delete a turn
    assert client.delete(
        f"/v1/apps/prattletale/conversations/{cid}/turns/{user_turn['id']}"
    ).status_code == 204
    assert not any(t["id"] == user_turn["id"] for t in store.get_transcript(cid)["turns"])
