"""SP3 — the Summarizer plugin's ``summarize`` action through SP1's dispatch.

Stubbed executor (fixed summary text) + stubbed counterpart. Asserts the action
posts exactly one ``summary`` turn (no model reply), Keep vs. Purge behaviour, bad
params 4xx, and that the plugin advertises ``default_enabled=true``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import generator, store
from app.apps.prattletale.plugins.summarizer import plugin as summ_plugin
from app.apps.prattletale.plugins.summarizer import summarize
from app.chain.models import ChainLLMConfig
from app.main import app
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "mara-okafor", "name": "Mara"}
_SUMMARY = "They argued about the missing key, then made up."


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")
    monkeypatch.setattr(summ_plugin, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )

    async def fake_chain(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(_SUMMARY, encoding="utf-8")

    monkeypatch.setattr(summarize, "execute_chain_job", fake_chain)


def _seed(enabled=True) -> str:
    conv = store.create_conversation({
        "title": "Diner",
        "counterpart_character_id": "mara-okafor",
        "config": {"enabled_plugins": ["summarizer"] if enabled else []},
    })
    cid = conv["id"]
    store.append_user_turn(cid, [{"type": "dialogue", "text": "where's the key"}])
    store.append_model_turn(cid, [{"type": "dialogue", "text": "i lost it"}])
    store.append_user_turn(cid, [{"type": "dialogue", "text": "seriously?"}])
    return cid


def _dispatch(client, cid, body):
    return client.post(
        f"/v1/apps/prattletale/conversations/{cid}/plugins/summarizer/actions/summarize",
        json=body,
    )


# --- manifest --------------------------------------------------------------

def test_summarizer_listed_default_on(client):
    r = client.get("/v1/apps/prattletale/plugins")
    m = {p["id"]: p for p in r.json()["plugins"]}
    assert "summarizer" in m
    assert m["summarizer"]["default_enabled"] is True
    assert m["summarizer"]["actions"] == ["summarize"]


# --- happy path: one summary turn, no model reply --------------------------

def test_keep_posts_one_summary_turn_no_reply(client):
    cid = _seed()
    r = _dispatch(client, cid, {"mode": "keep", "detail": "standard", "focus": ""})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["mode"] == "keep"
    assert res["hidden_item_ids"] == []
    assert res["summary_turn"]["author"] == "system"
    items = res["summary_turn"]["items"]
    assert len(items) == 1 and items[0]["type"] == "summary"
    assert items[0]["text"] == _SUMMARY

    transcript = store.get_transcript(cid)
    last = transcript["turns"][-1]
    assert last["author"] == "system"
    # 3 seeded turns + 1 summary, no extra model reply.
    assert len(transcript["turns"]) == 4


def test_keep_leaves_originals_in_context(client):
    cid = _seed()
    _dispatch(client, cid, {"mode": "keep", "detail": "brief", "focus": ""})
    conversation = store.get_conversation(cid)
    transcript = store.get_transcript(cid)
    flat = generator.build_context(conversation, dict(_CHARACTER), transcript)["transcript"]
    assert "where's the key" in flat
    assert "i lost it" in flat
    assert "[Summary so far] " + _SUMMARY in flat


# --- purge: covered originals hidden, summary carries forward ---------------

def test_purge_hides_covered_originals(client):
    cid = _seed()
    r = _dispatch(client, cid, {"mode": "purge", "detail": "detailed", "focus": "the key"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["mode"] == "purge"
    # all three seeded items covered + hidden
    assert len(res["hidden_item_ids"]) == 3

    transcript = store.get_transcript(cid)
    # originals remain in the stored transcript (just hidden)
    assert len(transcript["turns"]) == 4
    hidden = [it for t in transcript["turns"] for it in t["items"] if it.get("hidden_from_context")]
    assert len(hidden) == 3

    # next context shows only the summary, not the originals
    conversation = store.get_conversation(cid)
    flat = generator.build_context(conversation, dict(_CHARACTER), transcript)["transcript"]
    assert flat.strip() == "[Summary so far] " + _SUMMARY
    assert "where's the key" not in flat


# --- bad params ------------------------------------------------------------

def test_bad_mode_422(client):
    cid = _seed()
    r = _dispatch(client, cid, {"mode": "nuke", "detail": "standard"})
    assert r.status_code == 422


def test_bad_detail_422(client):
    cid = _seed()
    r = _dispatch(client, cid, {"mode": "keep", "detail": "epic"})
    assert r.status_code == 422


def test_disabled_plugin_409(client):
    cid = _seed(enabled=False)
    r = _dispatch(client, cid, {"mode": "keep", "detail": "standard"})
    assert r.status_code == 409


# --- nothing to summarize --------------------------------------------------

def test_empty_history_422(client, monkeypatch):
    conv = store.create_conversation({
        "title": "Empty", "counterpart_character_id": "mara-okafor",
        "config": {"enabled_plugins": ["summarizer"]},
    })
    r = _dispatch(client, conv["id"], {"mode": "keep", "detail": "standard"})
    assert r.status_code == 422
