"""SP1 — transcript editing API (edit / hide / delete). Store ops + router 404s.

No LLM, no network: store ops monkeypatch ``CONVERSATIONS_DIR``; the router tests
drive the edit/delete endpoints over ``TestClient``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import generator, router as router_module, store
from app.main import app

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture(autouse=True)
def _tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")


@pytest.fixture()
def client():
    return TestClient(app)


def _seed() -> str:
    conv = store.create_conversation({
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
    })
    return conv["id"]


# --- store: edit_item -------------------------------------------------------

def test_edit_item_changes_only_text_and_round_trips():
    cid = _seed()
    turn = store.append_model_turn(cid, [
        {"type": "narration", "text": "She sighs."},
        {"type": "dialogue", "text": "old text"},
    ], job_id="j")
    item_id = turn["items"][1]["id"]

    updated = store.edit_item(cid, turn["id"], item_id, "new text")
    edited = updated["items"][1]
    assert edited["text"] == "new text"
    assert edited["id"] == item_id  # id unchanged
    assert edited["type"] == "dialogue"  # type unchanged
    assert edited["audio"] is None
    # round-trips via get_transcript
    disk = store.get_transcript(cid)["turns"][0]["items"][1]
    assert disk["text"] == "new text"
    # the sibling item is untouched
    assert store.get_transcript(cid)["turns"][0]["items"][0]["text"] == "She sighs."


def test_edit_item_missing_returns_none():
    cid = _seed()
    turn = store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    assert store.edit_item(cid, turn["id"], "t9999-i99", "x") is None
    assert store.edit_item(cid, "t9999", turn["items"][0]["id"], "x") is None
    assert store.edit_item("nope", turn["id"], turn["items"][0]["id"], "x") is None


# --- store: set_item_hidden -------------------------------------------------

def test_hidden_item_excluded_from_built_context(monkeypatch):
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))
    cid = _seed()
    turn = store.append_model_turn(cid, [
        {"type": "dialogue", "text": "keep me"},
        {"type": "dialogue", "text": "hide me"},
    ], job_id="j")
    item_id = turn["items"][1]["id"]

    store.set_item_hidden(cid, turn["id"], item_id, True)

    conversation = store.get_conversation(cid)
    transcript = store.get_transcript(cid)
    ctx = generator.build_context(conversation, dict(_CHARACTER), transcript)
    assert "keep me" in ctx["transcript"]
    assert "hide me" not in ctx["transcript"]

    # toggling back restores it to context
    store.set_item_hidden(cid, turn["id"], item_id, False)
    ctx2 = generator.build_context(conversation, dict(_CHARACTER), store.get_transcript(cid))
    assert "hide me" in ctx2["transcript"]


# --- store: delete_item / delete_turn ---------------------------------------

def test_delete_item_leaves_turn_when_others_remain():
    cid = _seed()
    turn = store.append_model_turn(cid, [
        {"type": "narration", "text": "a"},
        {"type": "dialogue", "text": "b"},
    ], job_id="j")
    result = store.delete_item(cid, turn["id"], turn["items"][0]["id"])
    assert "turn_deleted" not in result
    assert [it["text"] for it in result["items"]] == ["b"]
    assert len(store.get_transcript(cid)["turns"]) == 1


def test_delete_only_item_drops_the_turn():
    cid = _seed()
    store.append_user_turn(cid, [{"type": "dialogue", "text": "first"}])
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "only"}], job_id="j")
    result = store.delete_item(cid, turn["id"], turn["items"][0]["id"])
    assert result == {"turn_deleted": turn["id"]}
    remaining = store.get_transcript(cid)["turns"]
    assert [t["id"] for t in remaining] == ["t0001"]


def test_delete_item_missing_returns_none():
    cid = _seed()
    turn = store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    assert store.delete_item(cid, turn["id"], "t9999-i99") is None
    assert store.delete_item(cid, "t9999", turn["items"][0]["id"]) is None
    assert store.delete_item("nope", turn["id"], turn["items"][0]["id"]) is None


def test_delete_turn_keeps_other_ids_stable():
    cid = _seed()
    store.append_user_turn(cid, [{"type": "dialogue", "text": "one"}])
    mid = store.append_model_turn(cid, [{"type": "dialogue", "text": "two"}], job_id="j")
    store.append_user_turn(cid, [{"type": "dialogue", "text": "three"}])

    assert store.delete_turn(cid, mid["id"]) is True
    ids = [t["id"] for t in store.get_transcript(cid)["turns"]]
    assert ids == ["t0001", "t0003"]  # surviving ids unchanged (no renumber)
    # next_turn_seq stays monotonic
    assert store.get_transcript(cid)["next_turn_seq"] == 4


def test_delete_turn_missing_returns_false():
    cid = _seed()
    assert store.delete_turn(cid, "t9999") is False
    assert store.delete_turn("nope", "t0001") is False


# --- router endpoints -------------------------------------------------------

def test_patch_item_edits_text_via_endpoint(client):
    cid = _seed()
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "old"}], job_id="j")
    item_id = turn["items"][0]["id"]
    r = client.patch(
        f"/v1/apps/prattletale/conversations/{cid}/turns/{turn['id']}/items/{item_id}",
        json={"text": "new"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["text"] == "new"


def test_patch_item_toggles_hidden_via_endpoint(client):
    cid = _seed()
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "x"}], job_id="j")
    item_id = turn["items"][0]["id"]
    r = client.patch(
        f"/v1/apps/prattletale/conversations/{cid}/turns/{turn['id']}/items/{item_id}",
        json={"hidden_from_context": True},
    )
    assert r.status_code == 200
    assert r.json()["items"][0]["hidden_from_context"] is True


def test_patch_item_404s(client):
    cid = _seed()
    turn = store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    item_id = turn["items"][0]["id"]
    base = "/v1/apps/prattletale/conversations"
    assert client.patch(f"{base}/nope/turns/{turn['id']}/items/{item_id}", json={"text": "y"}).status_code == 404
    assert client.patch(f"{base}/{cid}/turns/t9999/items/{item_id}", json={"text": "y"}).status_code == 404
    assert client.patch(f"{base}/{cid}/turns/{turn['id']}/items/zzz", json={"text": "y"}).status_code == 404


def test_delete_item_endpoint_signals_turn_deletion(client):
    cid = _seed()
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "only"}], job_id="j")
    item_id = turn["items"][0]["id"]
    r = client.delete(
        f"/v1/apps/prattletale/conversations/{cid}/turns/{turn['id']}/items/{item_id}"
    )
    assert r.status_code == 200
    assert r.json() == {"turn_deleted": turn["id"]}
    assert store.get_transcript(cid)["turns"] == []


def test_delete_item_endpoint_404s(client):
    cid = _seed()
    turn = store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    base = "/v1/apps/prattletale/conversations"
    assert client.delete(f"{base}/{cid}/turns/{turn['id']}/items/zzz").status_code == 404
    assert client.delete(f"{base}/{cid}/turns/t9999/items/{turn['items'][0]['id']}").status_code == 404


def test_delete_turn_endpoint_204(client):
    cid = _seed()
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "x"}], job_id="j")
    r = client.delete(f"/v1/apps/prattletale/conversations/{cid}/turns/{turn['id']}")
    assert r.status_code == 204
    assert store.get_transcript(cid)["turns"] == []


def test_delete_turn_endpoint_404(client):
    cid = _seed()
    assert client.delete(f"/v1/apps/prattletale/conversations/{cid}/turns/t9999").status_code == 404
