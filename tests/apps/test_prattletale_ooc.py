"""The OOC plugin: the ``ooc`` item type, its exclusion from the in-character
context, the ``render_ooc_history`` side channel, and the ``send`` action through
the generic plugin dispatch.

An OOC message opens a parallel out-of-character exchange: ``send`` posts the
user's ``ooc`` turn AND the author's reply (a second ``ooc`` turn, author=model),
and returns both. In-character turns never see OOC content; OOC generation sees the
full OOC history. The chain executor and counterpart are stubbed so nothing needs
a GPU node.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import wildcards
from app.apps.prattletale import generator, store
from app.apps.prattletale.plugins import registry as plugin_registry
from app.apps.prattletale.plugins.ooc import generate as ooc_generate
from app.chain.models import ChainLLMConfig
from app.main import app
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "mara-okafor", "name": "Mara"}
_OOC_REPLY = "She's guarded here — let her deflect before she opens up."


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
    # OOC generation resolves the character + executor in its own module namespace.
    monkeypatch.setattr(ooc_generate, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )

    async def fake_chain(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(_OOC_REPLY, encoding="utf-8")

    monkeypatch.setattr(ooc_generate, "execute_chain_job", fake_chain)


def _seed(enabled=True) -> str:
    conv = store.create_conversation({
        "title": "Diner",
        "counterpart_character_id": "mara-okafor",
        "config": {"enabled_plugins": ["ooc"] if enabled else []},
    })
    cid = conv["id"]
    store.append_user_turn(cid, [{"type": "dialogue", "text": "what's good here"}])
    store.append_model_turn(cid, [{"type": "dialogue", "text": "the coffee"}])
    return cid


def _dispatch(client, cid, body):
    return client.post(
        f"/v1/apps/prattletale/conversations/{cid}/plugins/ooc/actions/send",
        json=body,
    )


# --- store: undecorated ooc item, both sides --------------------------------

def test_append_ooc_turn_user_is_raw():
    cid = _seed()
    turn = store.append_ooc_turn(cid, store.Author.user, "how should I play this?")
    assert turn["author"] == "user"
    items = turn["items"]
    assert len(items) == 1
    assert items[0]["type"] == "ooc"
    assert items[0]["status"] == "committed"
    # Freeform — never quote/asterisk-wrapped, even on the user side.
    assert items[0]["text"] == "how should I play this?"


def test_append_ooc_turn_model_side():
    cid = _seed()
    turn = store.append_ooc_turn(cid, store.Author.model, _OOC_REPLY, job_id="job-1")
    assert turn["author"] == "model"
    assert turn["job_id"] == "job-1"
    assert turn["items"][0]["type"] == "ooc"
    assert turn["items"][0]["text"] == _OOC_REPLY


# --- generator: OOC excluded from IC context, included in OOC history --------

def test_flatten_transcript_excludes_ooc():
    cid = _seed()
    store.append_ooc_turn(cid, store.Author.user, "how do I play this?")
    store.append_ooc_turn(cid, store.Author.model, _OOC_REPLY)
    transcript = store.get_transcript(cid)
    flat = generator._flatten_transcript(transcript["turns"], dict(_CHARACTER))
    assert "how do I play this?" not in flat
    assert _OOC_REPLY not in flat
    # In-character lines remain.
    assert "the coffee" in flat


def test_latest_user_text_skips_ooc():
    cid = _seed()
    store.append_ooc_turn(cid, store.Author.user, "should she be cold here?")
    transcript = store.get_transcript(cid)
    query = generator._latest_user_text(transcript["turns"])
    assert query == '"what\'s good here"'
    assert "should she be cold" not in query


def test_render_ooc_history_labels_both_sides():
    cid = _seed()
    store.append_ooc_turn(cid, store.Author.user, "how do I play this?")
    store.append_ooc_turn(cid, store.Author.model, _OOC_REPLY)
    transcript = store.get_transcript(cid)
    hist = generator.render_ooc_history(transcript["turns"])
    assert hist == f"[You] how do I play this?\n[Author] {_OOC_REPLY}"


def test_render_ooc_history_empty_when_none():
    cid = _seed()
    transcript = store.get_transcript(cid)
    assert generator.render_ooc_history(transcript["turns"]) == ""


def test_render_ooc_history_skips_hidden():
    cid = _seed()
    turn = store.append_ooc_turn(cid, store.Author.user, "a secret aside")
    store.set_item_hidden(cid, turn["id"], turn["items"][0]["id"], True)
    store.append_ooc_turn(cid, store.Author.user, "a visible aside")
    transcript = store.get_transcript(cid)
    hist = generator.render_ooc_history(transcript["turns"])
    assert "a secret aside" not in hist
    assert "[You] a visible aside" in hist


def test_render_ooc_history_spans_sessions():
    """A later OOC session carries the earlier one forward (whole transcript, not
    windowed) — even with an in-character exchange between them."""
    cid = _seed()
    store.append_ooc_turn(cid, store.Author.user, "first session")
    store.append_ooc_turn(cid, store.Author.model, "ok")
    store.append_user_turn(cid, [{"type": "dialogue", "text": "back in scene"}])
    store.append_model_turn(cid, [{"type": "dialogue", "text": "indeed"}])
    store.append_ooc_turn(cid, store.Author.user, "second session")
    transcript = store.get_transcript(cid)
    hist = generator.render_ooc_history(transcript["turns"])
    assert "[You] first session" in hist
    assert "[Author] ok" in hist
    assert "[You] second session" in hist
    # The in-character lines are not part of the OOC history.
    assert "back in scene" not in hist


# --- action happy path: user message + author reply -------------------------

def test_send_posts_user_and_author_turns(client):
    cid = _seed()
    r = _dispatch(client, cid, {"text": "how should I play this scene?"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ooc_user_turn"]["author"] == "user"
    assert res["ooc_user_turn"]["items"][0]["type"] == "ooc"
    assert res["ooc_user_turn"]["items"][0]["text"] == "how should I play this scene?"
    assert res["ooc_model_turn"]["author"] == "model"
    assert res["ooc_model_turn"]["items"][0]["type"] == "ooc"
    assert res["ooc_model_turn"]["items"][0]["text"] == _OOC_REPLY

    transcript = store.get_transcript(cid)
    # 2 seeded IC turns + ooc user + ooc model.
    assert len(transcript["turns"]) == 4
    assert [t["author"] for t in transcript["turns"][-2:]] == ["user", "model"]


def test_ooc_reply_absent_from_in_character_context(client):
    cid = _seed()
    _dispatch(client, cid, {"text": "how should I play this scene?"})
    conversation = store.get_conversation(cid)
    transcript = store.get_transcript(cid)
    flat = generator.build_context(conversation, dict(_CHARACTER), transcript)["transcript"]
    assert _OOC_REPLY not in flat
    assert "how should I play this scene?" not in flat


# --- generation failure: inline-error OOC turn, never raises ----------------

def test_generation_failure_posts_inline_error_turn(client, monkeypatch):
    """An empty model output must not 500 the request: the pipeline posts an
    inline-error OOC reply so the back-and-forth stays consistent."""
    async def empty_chain(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text("", encoding="utf-8")

    monkeypatch.setattr(ooc_generate, "execute_chain_job", empty_chain)
    cid = _seed()
    r = _dispatch(client, cid, {"text": "anything"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ooc_model_turn"]["author"] == "model"
    assert res["ooc_model_turn"]["items"][0]["type"] == "ooc"
    assert "OOC generation failed" in res["ooc_model_turn"]["items"][0]["text"]


# --- bad params -------------------------------------------------------------

def test_empty_text_422(client):
    cid = _seed()
    r = _dispatch(client, cid, {"text": "   "})
    assert r.status_code == 422


def test_disabled_plugin_409(client):
    cid = _seed(enabled=False)
    r = _dispatch(client, cid, {"text": "hi"})
    assert r.status_code == 409


def test_missing_conversation_404(client):
    r = _dispatch(client, "does-not-exist", {"text": "hi"})
    assert r.status_code == 404


# --- manifest + registry ----------------------------------------------------

def test_ooc_listed_default_on(client):
    r = client.get("/v1/apps/prattletale/plugins")
    m = {p["id"]: p for p in r.json()["plugins"]}
    assert "ooc" in m
    assert m["ooc"]["default_enabled"] is True
    assert m["ooc"]["actions"] == ["send"]


def test_ooc_module_registered():
    assert "app.apps.prattletale.plugins.ooc" in plugin_registry._PLUGIN_MODULES
    plugin_registry.seed_plugins()
    assert plugin_registry.get_plugin("ooc") is not None
