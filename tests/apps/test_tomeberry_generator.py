"""Phase 4 — Tomeberry generation pipeline (chain executor monkeypatched)."""

from __future__ import annotations

import pytest

import app.chain.oneshot as oneshot
from app.apps.tomeberry import generator, store


def _fake_executor(output: str):
    async def _exec(job_id, job_dir, request):
        (job_dir / "final_output.txt").write_text(output, encoding="utf-8")

    return _exec


# ---- build_mode_variables (pure) ------------------------------------------


def test_build_mode_variables_has_all_14_and_omits_empty():
    bundle = generator.build_mode_variables(
        mode="draft", tale_title="My Tale", author_instruction="write it"
    )
    assert set(bundle) == set(generator._THE_14)
    assert bundle["tale_title"] == "My Tale"
    assert bundle["author_instruction"] == "write it"
    # empty sections render to "" (no placeholder noise)
    assert bundle["premise"] == ""
    assert bundle["project_context"] == ""
    assert bundle["selected_text"] == ""
    # output_format + change_policy come from the spec (non-empty for draft)
    assert bundle["output_format"]
    assert bundle["change_policy"]


def test_build_mode_variables_labels_present_when_filled():
    bundle = generator.build_mode_variables(
        mode="revise",
        tale_title="T",
        author_instruction="x",
        premise_body="A hero falls.",
        selected_text="the old text",
        current_unit={"type": "scene", "title": "Sc", "body": "body words here", "metadata": {"word_count": 3}},
    )
    assert bundle["premise"].startswith("PREMISE:")
    assert "A hero falls." in bundle["premise"]
    assert bundle["selected_text"].startswith("SELECTED TEXT:")
    assert bundle["current_structural_unit"].startswith("CURRENT UNIT")


# ---- pipeline --------------------------------------------------------------


async def test_draft_creates_manuscript_proposal(monkeypatch):
    tale = store.create_tale({"title": "T", "premise": "A quest."})
    tid = tale["id"]
    scene = store.create_concept(
        tid, {"concept_class": "structural_unit", "type": "scene", "title": "Open", "body": "old prose"}
    )
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake_executor("brand new prose"))
    res = await generator.run_assistant_request(
        tid, {"text": "flesh this out", "mode": "draft", "current_unit_id": scene["id"]}
    )
    assert res["error"] is None
    assert res["proposal"] is not None
    assert res["proposal"]["status"] == "pending"
    # a textdiff proposal was persisted
    from app.textdiff import store as ds

    proposals = ds.list_proposals("tomeberry", f"{tid}/{scene['id']}")
    assert len(proposals) == 1
    assert proposals[0].after == "brand new prose"
    # trace records resolved + unresolved + substitutions
    trace = store.get_trace(tid, res["request_id"])
    assert trace["resolved_prompt"]
    assert trace["unresolved_template"]
    assert any(s["token"] == "{{var.author_instruction}}" for s in trace["variable_substitutions"])
    assert trace["proposal"]["after"] == "brand new prose"
    # the author + assistant messages are in the thread
    msgs = store.get_assistant(tid)["messages"]
    assert any(m["role"] == "user" for m in msgs)
    assert any(m["role"] == "assistant" and m["kind"] == "proposal" for m in msgs)


async def test_revise_parses_json_revised_text(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    scene = store.create_concept(
        tid, {"concept_class": "structural_unit", "type": "scene", "body": "rough draft"}
    )
    out = '{"revised_text": "a much better draft", "summary": "tightened pacing"}'
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake_executor(out))
    res = await generator.run_assistant_request(
        tid, {"text": "improve", "mode": "revise", "current_unit_id": scene["id"]}
    )
    from app.textdiff import store as ds

    p = ds.list_proposals("tomeberry", f"{tid}/{scene['id']}")[0]
    assert p.after == "a much better draft"
    # the summary becomes the assistant message text
    assistant = [m for m in store.get_assistant(tid)["messages"] if m["role"] == "assistant"][-1]
    assert "tightened pacing" in assistant["text"]


async def test_discover_is_chat_no_proposal(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake_executor("- idea one\n- idea two"))
    res = await generator.run_assistant_request(tid, {"text": "ideas?", "mode": "discover"})
    assert res["proposal"] is None
    assistant = [m for m in store.get_assistant(tid)["messages"] if m["role"] == "assistant"][-1]
    assert assistant["kind"] == "chat"
    assert "idea one" in assistant["text"]


async def test_develop_proposes_concept(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    out = '{"concept_class": "story_entity", "type": "character", "title": "Mara", "body": "a knight"}'
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake_executor(out))
    res = await generator.run_assistant_request(tid, {"text": "develop Mara", "mode": "develop"})
    assert res["proposal"] is not None
    assert res["proposal"]["scope"]["kind"] == "concept"
    assert res["proposal"]["payload"]["title"] == "Mara"


async def test_track_json_failure_degrades(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake_executor("not json — sorry"))
    res = await generator.run_assistant_request(tid, {"text": "extract", "mode": "track"})
    assert res["error"] is None  # never crashes
    trace = store.get_trace(tid, res["request_id"])
    assert trace["parsed"]["parse_error"] is not None


async def test_executor_failure_posts_error_message(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]

    async def _boom(job_id, job_dir, request):
        raise RuntimeError("llm exploded")

    monkeypatch.setattr(oneshot, "execute_chain_job", _boom)
    res = await generator.run_assistant_request(tid, {"text": "go", "mode": "draft"})
    assert res["error"] == "llm exploded"
    assistant = [m for m in store.get_assistant(tid)["messages"] if m["role"] == "assistant"][-1]
    assert assistant["kind"] == "status"
    assert "failed" in assistant["text"]


def test_request_route(client, monkeypatch):
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake_executor("some prose"))
    tid = client.post("/v1/apps/tomeberry/tales", json={"title": "Q"}).json()["id"]
    r = client.post(
        f"/v1/apps/tomeberry/tales/{tid}/requests",
        json={"text": "write", "mode": "draft"},
    )
    assert r.status_code == 200
    assert r.json()["error"] is None
    assert r.json()["request_id"]
    # 404 for missing tale
    assert client.post("/v1/apps/tomeberry/tales/none/requests", json={"text": "x"}).status_code == 404
