"""The Command plugin: the ``command`` item type, the standing-orders block it feeds,
and the ``send`` action through the generic plugin dispatch.

A command is a standing order (a switch), not a message: ``send`` posts a user
``command`` turn and generates **no** model reply. The order is injected into future
turns via the standing-orders block, gathered from the whole transcript. The chain
executor and counterpart are stubbed so nothing needs a GPU node.
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


# --- generator: standing-orders block ---------------------------------------

def test_flatten_transcript_excludes_command():
    """Commands are standing orders, injected as their own block — never inline in
    the conversation script."""
    cid = _seed()
    store.append_command_turn(cid, "answer only in French")
    transcript = store.get_transcript(cid)
    flat = generator._flatten_transcript(transcript["turns"], dict(_CHARACTER))
    assert "answer only in French" not in flat
    assert "USER COMMAND" not in flat


def test_render_standing_orders_is_a_mandatory_block():
    block = generator._render_standing_orders(["call me Alex", "be terse"])
    assert "STANDING ORDERS" in block
    assert "MUST obey" in block
    assert "- call me Alex" in block
    assert "- be terse" in block


def test_render_standing_orders_empty_when_none():
    assert generator._render_standing_orders([]) == ""


def test_build_context_carries_active_standing_orders():
    cid = _seed()
    store.append_command_turn(cid, "answer only in French")
    conv = store.get_conversation(cid)
    transcript = store.get_transcript(cid)
    ctx = generator.build_context(conv, dict(_CHARACTER), transcript)
    assert "STANDING ORDERS" in ctx["standing_orders"]
    assert "answer only in French" in ctx["standing_orders"]
    # The command does not also appear inline in the conversation script.
    assert "answer only in French" not in ctx["transcript"]


def test_standing_orders_persist_beyond_context_window():
    """An order set long ago must stay in force even once it scrolls past the
    context window: standing orders are gathered from the whole transcript."""
    cid = _seed()
    store.append_command_turn(cid, "answer only in French")
    # Push the command well outside a tiny window.
    for _ in range(5):
        store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
        store.append_model_turn(cid, [{"type": "dialogue", "text": "hey"}])
    conv = store.get_conversation(cid)
    conv["config"]["context_window_turns"] = 2
    transcript = store.get_transcript(cid)
    ctx = generator.build_context(conv, dict(_CHARACTER), transcript)
    assert "answer only in French" in ctx["standing_orders"]


def test_hidden_command_is_not_an_active_standing_order():
    cid = _seed()
    turn = store.append_command_turn(cid, "answer only in French")
    item = turn["items"][0]
    store.set_item_hidden(cid, turn["id"], item["id"], True)
    transcript = store.get_transcript(cid)
    orders = generator._collect_standing_orders(transcript["turns"])
    assert orders == []


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

def test_send_posts_command_with_no_model_reply(client):
    """Issuing a command flips a switch: it persists a command turn and returns it,
    and does NOT generate a partner reply."""
    cid = _seed()
    r = _dispatch(client, cid, {"text": "answer only in French"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["command_turn"]["author"] == "user"
    assert res["command_turn"]["items"][0]["type"] == "command"
    assert "model_turn" not in res

    transcript = store.get_transcript(cid)
    # 2 seeded turns + command turn — no model reply appended.
    assert len(transcript["turns"]) == 3
    assert transcript["turns"][-1]["author"] == "user"
    assert transcript["turns"][-1]["items"][0]["type"] == "command"


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
