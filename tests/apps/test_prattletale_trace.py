"""SP3 — trace + pipeline read API (dev-tools backend).

Runs a stubbed-executor model turn (the fake writes both ``final_output.txt`` and
per-step ``steps/NNN_<id>/output.txt`` so the enriched ``steps`` list captures
per-step output), then reads the trace back over the store + the HTTP endpoint.
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


def _seed(**config) -> str:
    conv = store.create_conversation({
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
        "config": config or {},
    })
    return conv["id"]


def _fake_chain(final_output: str):
    """Fake executor that scaffolds each request step's output dir + final output."""
    async def fake(job_id, job_dir, request, event_bus=None):
        steps_dir = job_dir / "steps"
        for step in request.steps:
            d = steps_dir / f"{step.number:03d}_{step.id}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "prompt.txt").write_text(f"rendered:{step.id}", encoding="utf-8")
            (d / "output.txt").write_text(f"out:{step.id}", encoding="utf-8")
        (job_dir / "final_output.txt").write_text(final_output, encoding="utf-8")
    return fake


async def test_trace_has_enriched_steps_with_variety(client, monkeypatch):
    cid = _seed(variety_pass_enabled=True)
    store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("[say] hey"))

    turn, job_id = await generator.run_model_turn(cid)

    r = client.get(f"/v1/apps/prattletale/conversations/{cid}/turns/{turn['id']}/trace")
    assert r.status_code == 200, r.text
    trace = r.json()
    assert trace["job_id"] == job_id
    assert trace["raw_final_output"] == "[say] hey"
    assert trace["context_input"]["transcript"].startswith('[User] "hi"')
    assert len(trace["parsed_items"]) == 1

    steps = trace["steps"]
    # The variety + guard steps are retired; the turn step stands alone.
    assert [s["id"] for s in steps] == ["turn"]
    assert [s["number"] for s in steps] == [1]
    # per-step output + prompt were captured from the step dirs
    assert steps[0]["output"] == "out:turn"
    assert steps[0]["prompt"] == "rendered:turn"


async def test_trace_step_count_drops_without_variety(client, monkeypatch):
    cid = _seed(variety_pass_enabled=False)
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("[say] yo"))

    turn, _ = await generator.run_model_turn(cid)
    trace = client.get(
        f"/v1/apps/prattletale/conversations/{cid}/turns/{turn['id']}/trace"
    ).json()
    assert [s["id"] for s in trace["steps"]] == ["turn"]


def test_trace_404_for_turn_without_trace(client):
    cid = _seed()
    store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    r = client.get(f"/v1/apps/prattletale/conversations/{cid}/turns/t0001/trace")
    assert r.status_code == 404


def test_trace_404_for_missing_conversation(client):
    r = client.get("/v1/apps/prattletale/conversations/nope/turns/t0001/trace")
    assert r.status_code == 404


def test_get_trace_and_list_traces_store_helpers(monkeypatch):
    cid = _seed()
    store.write_trace(cid, "t0002", {"job_id": "j", "raw_final_output": "x"})
    assert store.get_trace(cid, "t0002")["raw_final_output"] == "x"
    assert store.get_trace(cid, "t9999") is None
    assert store.list_traces(cid) == ["t0002"]
    assert store.list_traces("nope") == []


async def test_trace_carries_director_plan_pattern_and_messages(client, monkeypatch):
    cid = _seed()
    store.append_user_turn(cid, [{"type": "dialogue", "text": "you came back"}])

    async def fake(job_id, job_dir, request, event_bus=None):
        if request.steps[0].id == "director":
            (job_dir / "final_output.txt").write_text(
                '{"conversation_move": "tease", "length": "short"}', encoding="utf-8")
        else:
            (job_dir / "final_output.txt").write_text("[say] hi", encoding="utf-8")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    turn, _ = await generator.run_model_turn(cid)
    trace = store.get_trace(cid, turn["id"])
    assert trace["prompt_version"] == generator.PRATTLETALE_PROMPT_VERSION
    assert trace["director_plan"]["conversation_move"] == "tease"
    assert "tease" in trace["director_plan_raw"]
    assert isinstance(trace["pattern_summary"], dict)
    # structured mode (default) -> the role array is captured
    assert trace["structured_messages"] is not None
    assert any(m["role"] == "user" for m in trace["structured_messages"])
    assert trace["repair"]["llm_used"] is False


# --- prompt debug surface ---------------------------------------------------

def test_debug_prompts_lists_active_and_version(client):
    r = client.get("/v1/apps/prattletale/debug/prompts")
    assert r.status_code == 200
    body = r.json()
    assert body["prompt_version"] == generator.PRATTLETALE_PROMPT_VERSION
    assert set(body["prompts"]) == {"turn", "turn_system", "director", "repair"}
    assert "You are a real person" in body["prompts"]["turn_system"]["active_prompt"]
    assert "variety" in body["retired"] and "feel_director" in body["retired"]


def test_debug_reset_unknown_key_404(client):
    assert client.post("/v1/apps/prattletale/debug/prompts/nope/reset").status_code == 404


def test_debug_reset_falls_back_to_default(client):
    from app.prompt_pal import store as pp_store
    # edit the stored turn prompt, then reset it -> stored copy removed
    pp_store.create_entry({"app": "prattletale", "key": "turn", "title": "turn",
                           "prompt": "MY EDITED TURN"})
    assert pp_store.get_by_app_key("prattletale", "turn") is not None
    r = client.post("/v1/apps/prattletale/debug/prompts/turn/reset")
    assert r.status_code == 200 and r.json()["reset"] is True
    assert pp_store.get_by_app_key("prattletale", "turn") is None
    # nothing stored now -> a second reset is a no-op
    assert client.post("/v1/apps/prattletale/debug/prompts/turn/reset").json()["reset"] is False
