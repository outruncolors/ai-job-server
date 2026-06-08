"""SP4 — router / API. TestClient with a stubbed generator (no LLM, no GPU)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import router as router_module
from app.apps.prattletale import store
from app.main import app

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Conversations under tmp; counterpart present; the model turn stubbed."""
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(router_module, "get_character", lambda cid: dict(_CHARACTER))

    async def fake_model_turn(
        conversation_id, llm=None, *, replace_turn_id=None, add_version_turn_id=None, synthesize=True
    ):
        items = [
            {"type": "narration", "text": "She glances up."},
            {"type": "dialogue", "text": "Hey."},
        ]
        if add_version_turn_id is not None:
            turn = store.add_turn_version(conversation_id, add_version_turn_id, items, job_id="job_fake")
        elif replace_turn_id is not None:
            turn = store.replace_turn(conversation_id, replace_turn_id, items)
        else:
            turn = store.append_model_turn(conversation_id, items)
        return turn, "job_fake"

    monkeypatch.setattr(router_module, "run_model_turn", fake_model_turn)


def _create(client) -> dict:
    r = client.post(
        "/v1/apps/prattletale/conversations",
        json={
            "title": "Late-night diner",
            "counterpart_character_id": "mara-okafor",
            "scenario": "1am, rain outside.",
            "role_instructions": "Stay in character as Mara.",
            "device_user": {"display_name": "You", "persona": "A regular."},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- create / get / list / delete ------------------------------------------

def test_create_persists_both_files(client):
    conv = _create(client)
    conv_dir = store.CONVERSATIONS_DIR / conv["id"]
    assert (conv_dir / "conversation.json").exists()
    assert (conv_dir / "transcript.json").exists()
    assert conv["counterpart_character_id"] == "mara-okafor"


def test_create_missing_counterpart_404(client, monkeypatch):
    monkeypatch.setattr(router_module, "get_character", lambda cid: None)
    r = client.post(
        "/v1/apps/prattletale/conversations",
        json={"title": "Ghost", "counterpart_character_id": "nope"},
    )
    assert r.status_code == 404


def test_get_returns_conversation_and_transcript(client):
    conv = _create(client)
    r = client.get(f"/v1/apps/prattletale/conversations/{conv['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation"]["id"] == conv["id"]
    assert body["transcript"]["conversation_id"] == conv["id"]
    assert body["transcript"]["turns"] == []


def test_get_missing_404(client):
    assert client.get("/v1/apps/prattletale/conversations/nope").status_code == 404


def test_list_returns_summaries(client):
    conv = _create(client)
    listed = client.get("/v1/apps/prattletale/conversations").json()["conversations"]
    row = next(c for c in listed if c["id"] == conv["id"])
    assert row["title"] == "Late-night diner"
    assert "updated_at" in row


def test_delete_removes_folder(client):
    conv = _create(client)
    r = client.delete(f"/v1/apps/prattletale/conversations/{conv['id']}")
    assert r.status_code == 204
    assert not (store.CONVERSATIONS_DIR / conv["id"]).exists()
    assert client.get(f"/v1/apps/prattletale/conversations/{conv['id']}").status_code == 404


def test_delete_missing_404(client):
    assert client.delete("/v1/apps/prattletale/conversations/nope").status_code == 404


# --- turns -----------------------------------------------------------------

def test_post_turn_returns_user_and_model(client):
    conv = _create(client)
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns",
        json={"items": [{"type": "dialogue", "text": "you actually showed up"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_turn"]["author"] == "user"
    # User dialogue is stored in the canonical format (double-quoted).
    assert body["user_turn"]["items"][0]["text"] == '"you actually showed up"'
    assert body["model_turn"]["author"] == "model"
    assert [i["type"] for i in body["model_turn"]["items"]] == ["narration", "dialogue"]

    # both turns round-trip on disk
    transcript = client.get(f"/v1/apps/prattletale/conversations/{conv['id']}").json()["transcript"]
    assert [t["author"] for t in transcript["turns"]] == ["user", "model"]


def test_post_turn_resolves_tokens_in_user_text(client):
    # {{var.scenario}} is an in-scope chat var (generator.pt_scope_vars); it must
    # resolve when the message is sent, and an unknown var falls back to its literal.
    conv = _create(client)
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns",
        json={"items": [{"type": "dialogue", "text": "re: {{var.scenario}} and {{var.nope}}"}]},
    )
    assert r.status_code == 200, r.text
    text = r.json()["user_turn"]["items"][0]["text"]
    assert "1am, rain outside." in text
    assert "nope" in text and "{{var." not in text


def test_post_turn_missing_conversation_404(client):
    r = client.post(
        "/v1/apps/prattletale/conversations/nope/turns",
        json={"items": [{"type": "dialogue", "text": "hi"}]},
    )
    assert r.status_code == 404


# --- retry -----------------------------------------------------------------

def test_retry_replaces_error_turn_in_place(client):
    conv = _create(client)
    store.append_user_turn(conv["id"], [{"type": "dialogue", "text": "hello?"}])
    error_turn = store.append_error_turn(conv["id"], "boom")
    turn_id = error_turn["id"]
    assert error_turn["items"][0]["type"] == "system_error"

    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/{turn_id}/retry"
    )
    assert r.status_code == 200, r.text
    replaced = r.json()
    assert replaced["id"] == turn_id  # same id / position
    assert [i["type"] for i in replaced["items"]] == ["narration", "dialogue"]
    assert all(i["status"] == "committed" for i in replaced["items"])

    # the transcript has the replacement in place, not an extra appended turn
    transcript = store.get_transcript(conv["id"])
    assert [t["id"] for t in transcript["turns"]] == ["t0001", turn_id]
    assert transcript["turns"][-1]["items"][0]["type"] == "narration"


def test_retry_missing_turn_404(client):
    conv = _create(client)
    assert (
        client.post(f"/v1/apps/prattletale/conversations/{conv['id']}/turns/t9999/retry").status_code
        == 404
    )


def test_retry_non_latest_turn_409(client):
    conv = _create(client)
    user_turn = store.append_user_turn(conv["id"], [{"type": "dialogue", "text": "hi"}])
    store.append_error_turn(conv["id"], "boom")  # the latest turn
    # retrying the earlier user turn is rejected
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/{user_turn['id']}/retry"
    )
    assert r.status_code == 409


def test_retry_missing_conversation_404(client):
    assert (
        client.post("/v1/apps/prattletale/conversations/nope/turns/t0001/retry").status_code == 404
    )


# --- continue (partner takes another turn) ---------------------------------

def test_continue_appends_model_turn_without_user_turn(client):
    conv = _create(client)
    store.append_user_turn(conv["id"], [{"type": "dialogue", "text": "hi"}])
    r = client.post(f"/v1/apps/prattletale/conversations/{conv['id']}/continue")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "user_turn" not in body
    assert body["model_turn"]["author"] == "model"
    # only the original user turn + the new model turn — no extra user turn
    transcript = store.get_transcript(conv["id"])
    assert [t["author"] for t in transcript["turns"]] == ["user", "model"]


def test_continue_on_empty_conversation_lets_character_open(client):
    conv = _create(client)
    r = client.post(f"/v1/apps/prattletale/conversations/{conv['id']}/continue")
    assert r.status_code == 200, r.text
    assert store.get_transcript(conv["id"])["turns"][0]["author"] == "model"


def test_continue_missing_conversation_404(client):
    assert client.post("/v1/apps/prattletale/conversations/nope/continue").status_code == 404


# --- regenerate (versions) -------------------------------------------------

def test_regenerate_latest_model_turn_appends_version(client):
    conv = _create(client)
    store.append_user_turn(conv["id"], [{"type": "dialogue", "text": "hi"}])
    model_turn = store.append_model_turn(conv["id"], [{"type": "dialogue", "text": "original"}], job_id="j1")

    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/{model_turn['id']}/regenerate"
    )
    assert r.status_code == 200, r.text
    turn = r.json()
    assert len(turn["versions"]) == 2
    assert turn["active_version"] == 1
    # the original survives as v0; the turn keeps its id/position
    assert turn["id"] == model_turn["id"]
    assert turn["versions"][0]["items"][0]["text"] == "original"
    transcript = store.get_transcript(conv["id"])
    assert [t["id"] for t in transcript["turns"]] == ["t0001", model_turn["id"]]


def test_regenerate_non_latest_turn_409(client):
    conv = _create(client)
    user_turn = store.append_user_turn(conv["id"], [{"type": "dialogue", "text": "hi"}])
    store.append_model_turn(conv["id"], [{"type": "dialogue", "text": "reply"}])  # the latest turn
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/{user_turn['id']}/regenerate"
    )
    assert r.status_code == 409


def test_regenerate_missing_turn_404(client):
    conv = _create(client)
    assert (
        client.post(
            f"/v1/apps/prattletale/conversations/{conv['id']}/turns/t9999/regenerate"
        ).status_code == 404
    )


# --- version switch --------------------------------------------------------

def test_select_version_switches_active(client):
    conv = _create(client)
    model_turn = store.append_model_turn(conv["id"], [{"type": "dialogue", "text": "v0"}], job_id="j1")
    store.add_turn_version(conv["id"], model_turn["id"], [{"type": "dialogue", "text": "v1"}], job_id="j2")

    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/{model_turn['id']}/version",
        json={"index": 0},
    )
    assert r.status_code == 200, r.text
    turn = r.json()
    assert turn["active_version"] == 0
    assert turn["items"][0]["text"] == "v0"


def test_select_version_out_of_range_422(client):
    conv = _create(client)
    model_turn = store.append_model_turn(conv["id"], [{"type": "dialogue", "text": "v0"}], job_id="j1")
    store.add_turn_version(conv["id"], model_turn["id"], [{"type": "dialogue", "text": "v1"}], job_id="j2")
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/{model_turn['id']}/version",
        json={"index": 9},
    )
    assert r.status_code == 422


def test_select_version_unversioned_turn_422(client):
    conv = _create(client)
    model_turn = store.append_model_turn(conv["id"], [{"type": "dialogue", "text": "only"}])
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/{model_turn['id']}/version",
        json={"index": 0},
    )
    assert r.status_code == 422


def test_select_version_missing_turn_404(client):
    conv = _create(client)
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/turns/t9999/version",
        json={"index": 0},
    )
    assert r.status_code == 404
