"""The SFX plugin's resolve/clear actions + the conversation SFX config + that
the descriptor lands on the item without disturbing existing audio."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import store
from app.apps.prattletale.plugins.sfx import plugin as sfx_plugin
from app.main import app
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "ash", "name": "Ash",
              "speaking_style": {"sfx": {"emotes_identity": "young_woman", "enabled": True}}}

_RESOLVED = {"schema_version": 1, "status": "resolved", "effect_id": "yw_sneeze_01",
             "pack_id": "test_emotes", "profile_id": "young_woman",
             "path": "normalized/test_emotes/files/yw_sneeze_01.wav",
             "url": "/v1/sfx/file/normalized/test_emotes/files/yw_sneeze_01.wav",
             "duration_ms": 800, "created_at": "2026-05-31T00:00:00Z",
             "selection": {"category": "sneeze"}}


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")
    monkeypatch.setattr(sfx_plugin, "get_character", lambda cid: dict(_CHARACTER))

    captured = {}

    async def fake_resolve(**kwargs):
        captured.update(kwargs)
        return dict(_RESOLVED), {"result": dict(_RESOLVED)}
    monkeypatch.setattr(sfx_plugin.resolver, "resolve_sfx", fake_resolve)
    return captured


def _seed(sfx_enabled=True) -> str:
    conv = store.create_conversation({
        "title": "Scene", "counterpart_character_id": "ash",
        "config": {"enabled_plugins": ["sfx"], "sfx_enabled": sfx_enabled,
                   "sfx_chance": 0.5, "sfx_domains": ["lewd"]},
    })
    cid = conv["id"]
    store.append_model_turn(cid, [
        {"type": "action", "text": "she sneezes"},
        {"type": "dialogue", "text": "excuse me"},
    ])
    return cid


def _dispatch(client, cid, action, body):
    return client.post(
        f"/v1/apps/prattletale/conversations/{cid}/plugins/sfx/actions/{action}", json=body)


def test_resolve_turn_only_eligible_items(client, _isolate):
    cid = _seed()
    turn_id = store.get_transcript(cid)["turns"][0]["id"]
    r = _dispatch(client, cid, "resolve-turn", {"turn_id": turn_id})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1  # the action, not the dialogue
    # The resolver received the character identity + the conversation's domains/chance.
    assert _isolate["identity"] == "young_woman"
    assert _isolate["domains"] == ["lewd"]
    assert _isolate["chance"] == 0.5
    # Descriptor persisted on the item; the dialogue item is untouched.
    items_now = store.get_transcript(cid)["turns"][0]["items"]
    assert items_now[0]["sfx"]["status"] == "resolved"
    assert items_now[1].get("sfx") is None


def test_resolve_item_disabled_persists_skipped(client, _isolate):
    cid = _seed(sfx_enabled=False)
    turn = store.get_transcript(cid)["turns"][0]
    r = _dispatch(client, cid, "resolve-item",
                  {"turn_id": turn["id"], "item_id": turn["items"][0]["id"]})
    assert r.status_code == 200
    assert r.json()["sfx"]["status"] == "skipped"
    assert r.json()["sfx"]["reason"] == "disabled"


def test_resolve_item_keeps_audio_and_honours_final_state(client, _isolate):
    cid = _seed()
    turn = store.get_transcript(cid)["turns"][0]
    iid = turn["items"][0]["id"]
    store.apply_audio(cid, turn["id"], {iid: {"path": "media/x.wav", "duration_ms": 500}})

    first = _dispatch(client, cid, "resolve-item", {"turn_id": turn["id"], "item_id": iid})
    assert first.json()["sfx"]["status"] == "resolved"
    # audio still present alongside sfx
    item = store.get_transcript(cid)["turns"][0]["items"][0]
    assert item["audio"]["path"] == "media/x.wav" and item["sfx"]["status"] == "resolved"

    # Re-resolving without force returns the existing descriptor (no re-roll).
    again = _dispatch(client, cid, "resolve-item", {"turn_id": turn["id"], "item_id": iid})
    assert again.json()["sfx"]["status"] == "resolved"


def test_clear_item(client, _isolate):
    cid = _seed()
    turn = store.get_transcript(cid)["turns"][0]
    iid = turn["items"][0]["id"]
    _dispatch(client, cid, "resolve-item", {"turn_id": turn["id"], "item_id": iid})
    r = _dispatch(client, cid, "clear-item", {"turn_id": turn["id"], "item_id": iid})
    assert r.status_code == 200 and r.json()["sfx"] is None
    assert store.get_transcript(cid)["turns"][0]["items"][0]["sfx"] is None


def test_config_roundtrip(client):
    cid = _seed(sfx_enabled=False)
    r = client.patch(f"/v1/apps/prattletale/conversations/{cid}",
                     json={"config": {"sfx_enabled": True, "sfx_chance": 0.8,
                                      "sfx_domains": ["lewd"]}})
    assert r.status_code == 200
    cfg = store.get_conversation(cid)["config"]
    assert cfg["sfx_enabled"] is True and cfg["sfx_chance"] == 0.8
    assert cfg["sfx_domains"] == ["lewd"]
