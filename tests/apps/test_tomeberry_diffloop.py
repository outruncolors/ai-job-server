"""Phase 5 — propose / accept / reject / iterate."""

from __future__ import annotations

import app.chain.oneshot as oneshot
from app.apps.tomeberry import generator, store


def _fake(output: str):
    async def _exec(job_id, job_dir, request):
        (job_dir / "final_output.txt").write_text(output, encoding="utf-8")

    return _exec


async def test_accept_manuscript_diff_writes_body(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    scene = store.create_concept(tid, {"concept_class": "structural_unit", "type": "scene", "body": "old"})
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake("the new body"))
    res = await generator.run_assistant_request(tid, {"text": "rewrite", "mode": "draft", "current_unit_id": scene["id"]})
    rid = res["request_id"]
    out = await generator.accept_request(tid, rid)
    assert out["concept_id"] == scene["id"]
    assert store.get_concept(tid, scene["id"])["body"] == "the new body"
    # proposal marked accepted; concept history records it
    msg = store.find_request_message(tid, rid)
    assert msg["proposal"]["status"] == "accepted"
    assert store.get_trace(tid, rid)["user_action"] == "accepted"
    hist = store.get_concept(tid, scene["id"])["history"]
    assert any(h["kind"] == "accepted" for h in hist)


async def test_accept_selection_replaces_in_body(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    scene = store.create_concept(
        tid, {"concept_class": "structural_unit", "type": "scene", "body": "alpha beta gamma"}
    )
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake("BETA"))
    res = await generator.run_assistant_request(
        tid,
        {
            "text": "punch it up", "mode": "draft", "current_unit_id": scene["id"],
            "scope": {"kind": "selection", "selected_text": "beta"},
        },
    )
    await generator.accept_request(tid, res["request_id"])
    assert store.get_concept(tid, scene["id"])["body"] == "alpha BETA gamma"


async def test_reject_leaves_body_untouched(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    scene = store.create_concept(tid, {"concept_class": "structural_unit", "type": "scene", "body": "keep me"})
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake("discard me"))
    res = await generator.run_assistant_request(tid, {"text": "x", "mode": "draft", "current_unit_id": scene["id"]})
    generator.reject_request(tid, res["request_id"])
    assert store.get_concept(tid, scene["id"])["body"] == "keep me"
    assert store.find_request_message(tid, res["request_id"])["proposal"]["status"] == "rejected"
    # the full before/after still inspectable in the textdiff store
    from app.textdiff import store as ds

    assert ds.list_proposals("tomeberry", f"{tid}/{scene['id']}")[0].after == "discard me"


async def test_accept_concept_payload_creates_concepts(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    out = '{"concept_class": "story_entity", "type": "character", "title": "Mara", "body": "a knight"}'
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake(out))
    res = await generator.run_assistant_request(tid, {"text": "develop", "mode": "develop"})
    accepted = await generator.accept_request(tid, res["request_id"])
    ids = accepted["created_concept_ids"]
    assert len(ids) == 1
    c = store.get_concept(tid, ids[0])
    assert c["title"] == "Mara"
    assert c["metadata"]["model_generated"] is True


async def test_iterate_threads_prior_and_supersedes(monkeypatch):
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    scene = store.create_concept(tid, {"concept_class": "structural_unit", "type": "scene", "body": "v0"})
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake("attempt one"))
    first = await generator.run_assistant_request(tid, {"text": "draft", "mode": "draft", "current_unit_id": scene["id"]})

    captured = {}

    def _fake_capture(output):
        async def _exec(job_id, job_dir, request):
            captured["input"] = request.input
            (job_dir / "final_output.txt").write_text(output, encoding="utf-8")

        return _exec

    monkeypatch.setattr(oneshot, "execute_chain_job", _fake_capture("attempt two"))
    second = await generator.iterate_request(tid, first["request_id"], "make it darker")
    assert second["error"] is None
    # prior proposal superseded
    assert store.find_request_message(tid, first["request_id"])["proposal"]["status"] == "superseded"
    assert store.get_trace(tid, first["request_id"])["user_action"] == "iterated"
    # the new attempt threaded the prior output + feedback into the instruction
    assert "attempt one" in captured["input"]
    assert "make it darker" in captured["input"]
    # second proposal links back via iterate_of
    assert store.get_trace(tid, second["request_id"])["iterate_of"] == first["request_id"]


def test_diffloop_routes(client, monkeypatch):
    monkeypatch.setattr(oneshot, "execute_chain_job", _fake("routed prose"))
    tid = client.post("/v1/apps/tomeberry/tales", json={"title": "Q"}).json()["id"]
    bundle = client.get(f"/v1/apps/tomeberry/tales/{tid}").json()
    root = bundle["tale"]["structural_root_id"]
    sc = client.post(
        f"/v1/apps/tomeberry/tales/{tid}/concepts",
        json={"concept_class": "structural_unit", "type": "scene", "body": "before", "parent_id": root},
    ).json()["id"]
    rid = client.post(
        f"/v1/apps/tomeberry/tales/{tid}/requests",
        json={"text": "write", "mode": "draft", "current_unit_id": sc},
    ).json()["request_id"]
    # accept via route
    r = client.post(f"/v1/apps/tomeberry/tales/{tid}/requests/{rid}/accept")
    assert r.status_code == 200
    assert client.get(f"/v1/apps/tomeberry/tales/{tid}/concepts/{sc}").json()["body"] == "routed prose"
    # iterate via route
    r2 = client.post(f"/v1/apps/tomeberry/tales/{tid}/requests/{rid}/iterate", json={"text": "again"})
    assert r2.status_code == 200
    # reject the new one
    rid2 = r2.json()["request_id"]
    assert client.post(f"/v1/apps/tomeberry/tales/{tid}/requests/{rid2}/reject").status_code == 200
    # 404 for unknown request
    assert client.post(f"/v1/apps/tomeberry/tales/{tid}/requests/nope/accept").status_code == 404
