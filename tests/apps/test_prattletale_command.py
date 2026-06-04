"""The Command plugin: the ``command`` item type, its transcript directive, and the
``send`` action through the generic plugin dispatch.

The chain executor is stubbed (fixed reply text) and the counterpart is stubbed, so
``send`` posts a user ``command`` turn followed by a model reply with no GPU node.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import wildcards
from app.apps.prattletale import generator, store
from app.apps.prattletale.plugins import registry as plugin_registry
from app.chain.models import ChainLLMConfig
from app.main import app
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "mara-okafor", "name": "Mara"}
_REPLY = "[say] oui, comme tu veux."


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")
    monkeypatch.setattr(wildcards, "_DIR", tmp_path / "wildcards")
    monkeypatch.setattr(wildcards, "_INDEX_PATH", tmp_path / "wildcards" / "index.json")
    # Register the plugins (bare TestClient does not run the lifespan that seeds them).
    plugin_registry.seed_plugins()
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )

    async def fake_chain(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(_REPLY, encoding="utf-8")

    monkeypatch.setattr(generator, "execute_chain_job", fake_chain)


def _seed(enabled=True) -> str:
    conv = store.create_conversation({
        "title": "Diner",
        "counterpart_character_id": "mara-okafor",
        "config": {"enabled_plugins": ["command"] if enabled else []},
    })
    cid = conv["id"]
    store.append_user_turn(cid, [{"type": "dialogue", "text": "speak only in english"}])
    store.append_model_turn(cid, [{"type": "dialogue", "text": "sure"}])
    return cid


def _dispatch(client, cid, body):
    return client.post(
        f"/v1/apps/prattletale/conversations/{cid}/plugins/command/actions/send",
        json=body,
    )


# --- store: undecorated user command item ----------------------------------

def test_append_command_turn_is_undecorated_user_item():
    cid = _seed()
    turn = store.append_command_turn(cid, "answer only in French")
    assert turn["author"] == "user"
    items = turn["items"]
    assert len(items) == 1
    assert items[0]["type"] == "command"
    assert items[0]["status"] == "committed"
    # NOT quote/asterisk-wrapped (locks the _canonical_user_text fallthrough).
    assert items[0]["text"] == "answer only in French"


# --- generator: self-describing directive ----------------------------------

def test_render_item_command_is_a_mandatory_directive():
    line = generator._render_item({"type": "command", "text": "call me Alex"})
    assert "must obey" in line
    assert "call me Alex" in line
    assert line.startswith("[USER COMMAND")


def test_flatten_transcript_includes_command_directive():
    cid = _seed()
    store.append_command_turn(cid, "answer only in French")
    transcript = store.get_transcript(cid)
    flat = generator._flatten_transcript(transcript["turns"], dict(_CHARACTER))
    assert "USER COMMAND" in flat
    assert "answer only in French" in flat


def test_latest_user_text_skips_command():
    """A command is an instruction, not 'what the user said' — the memory query
    falls back to the prior real utterance."""
    cid = _seed()
    store.append_command_turn(cid, "answer only in French")
    transcript = store.get_transcript(cid)
    query = generator._latest_user_text(transcript["turns"])
    # User dialogue is stored canonicalized (quote-wrapped); the point is it's the
    # prior utterance, not the command directive.
    assert query == '"speak only in english"'
    assert "USER COMMAND" not in query


# --- action happy path ------------------------------------------------------

def test_send_posts_command_then_model_reply(client):
    cid = _seed()
    r = _dispatch(client, cid, {"text": "answer only in French"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["command_turn"]["author"] == "user"
    assert res["command_turn"]["items"][0]["type"] == "command"
    assert res["model_turn"]["author"] == "model"

    transcript = store.get_transcript(cid)
    # 2 seeded turns + command turn + model reply.
    assert len(transcript["turns"]) == 4
    assert transcript["turns"][-2]["items"][0]["type"] == "command"
    assert transcript["turns"][-1]["author"] == "model"
    assert transcript["turns"][-1]["items"][0]["text"]


# --- bad params -------------------------------------------------------------

def test_empty_text_422(client):
    cid = _seed()
    r = _dispatch(client, cid, {"text": "   "})
    assert r.status_code == 422


def test_disabled_plugin_409(client):
    cid = _seed(enabled=False)
    r = _dispatch(client, cid, {"text": "obey"})
    assert r.status_code == 409


def test_missing_conversation_404(client):
    r = _dispatch(client, "does-not-exist", {"text": "obey"})
    assert r.status_code == 404


# --- manifest + registry ----------------------------------------------------

def test_command_listed_default_on(client):
    r = client.get("/v1/apps/prattletale/plugins")
    m = {p["id"]: p for p in r.json()["plugins"]}
    assert "command" in m
    assert m["command"]["default_enabled"] is True
    assert m["command"]["actions"] == ["send"]


def test_command_module_registered():
    assert "app.apps.prattletale.plugins.command" in plugin_registry._PLUGIN_MODULES
    plugin_registry.seed_plugins()
    assert plugin_registry.get_plugin("command") is not None
