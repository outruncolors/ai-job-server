"""SP6 — Summarizer end-to-end + edge cases across the plugin surface.

A faithful stubbed executor (records each rendered prompt, emits a distinct
summary per call) lets these assert on-disk transcript shapes and that folding /
purge behave: a re-summarize after a purge covers the prior summary + new turns,
not the purged originals.
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


@pytest.fixture()
def client():
    return TestClient(app)


class _Executor:
    """Records the rendered prompt of each summary job; emits SUMMARY-1, -2, …"""

    def __init__(self):
        self.prompts: list[str] = []

    def install(self, monkeypatch):
        async def fake(job_id, job_dir, request, event_bus=None):
            self.prompts.append(request.input)
            n = len(self.prompts)
            (job_dir / "final_output.txt").write_text(f"SUMMARY-{n}", encoding="utf-8")
        monkeypatch.setattr(summarize, "execute_chain_job", fake)


@pytest.fixture()
def ex(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")
    monkeypatch.setattr(summ_plugin, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )
    e = _Executor()
    e.install(monkeypatch)
    return e


def _seed() -> str:
    conv = store.create_conversation({
        "title": "Diner", "counterpart_character_id": "mara-okafor",
        "config": {"enabled_plugins": ["summarizer"]},
    })
    cid = conv["id"]
    store.append_user_turn(cid, [{"type": "dialogue", "text": "where's the key"}])
    store.append_model_turn(cid, [{"type": "dialogue", "text": "i lost it"}])
    store.append_user_turn(cid, [{"type": "dialogue", "text": "seriously"}])
    return cid


def _dispatch(client, cid, body):
    return client.post(
        f"/v1/apps/prattletale/conversations/{cid}/plugins/summarizer/actions/summarize",
        json=body,
    )


def _ctx_transcript(cid) -> str:
    conv = store.get_conversation(cid)
    transcript = store.get_transcript(cid)
    return generator.build_context(conv, dict(_CHARACTER), transcript)["transcript"]


# --- the full integration scenario -----------------------------------------

def test_purge_then_resummarize_folds_prior_summary(client, ex):
    cid = _seed()

    # 1) purge / standard / focus → one summary turn, originals hidden.
    r = _dispatch(client, cid, {"mode": "purge", "detail": "standard", "focus": "the key"})
    assert r.status_code == 200, r.text
    assert r.json()["summary_turn"]["items"][0]["text"] == "SUMMARY-1"

    transcript = store.get_transcript(cid)
    assert len(transcript["turns"]) == 4  # 3 originals (hidden) + summary
    assert sum(1 for t in transcript["turns"] for it in t["items"]
               if it.get("hidden_from_context")) == 3

    # build_context now shows only the summary, not the purged originals.
    flat = _ctx_transcript(cid)
    assert flat.strip() == "[Summary so far] SUMMARY-1"

    # the focus note + detail reached the (first) summary prompt
    assert "the key" in ex.prompts[0]
    assert "where's the key" in ex.prompts[0]  # originals were summarized the first time

    # 2) add a user + model turn, then re-summarize.
    store.append_user_turn(cid, [{"type": "dialogue", "text": "found it in the car"}])
    store.append_model_turn(cid, [{"type": "dialogue", "text": "knew you would"}])

    r2 = _dispatch(client, cid, {"mode": "keep", "detail": "brief", "focus": ""})
    assert r2.status_code == 200, r2.text
    assert r2.json()["summary_turn"]["items"][0]["text"] == "SUMMARY-2"

    # The second summarize folded the prior summary + the NEW turns, and did NOT
    # re-include the purged originals.
    second_prompt = ex.prompts[1]
    assert "SUMMARY-1" in second_prompt
    assert "found it in the car" in second_prompt
    assert "knew you would" in second_prompt
    assert "where's the key" not in second_prompt  # purged originals stay out


# --- purge then unhide one covered item restores it to context --------------

def test_unhide_one_purged_item_restores_it(client, ex):
    cid = _seed()
    r = _dispatch(client, cid, {"mode": "purge", "detail": "standard", "focus": ""})
    hidden_ids = r.json()["hidden_item_ids"]
    assert len(hidden_ids) == 3

    # Unhide the first covered item (the user's "where's the key").
    transcript = store.get_transcript(cid)
    first_turn = transcript["turns"][0]
    store.set_item_hidden(cid, first_turn["id"], first_turn["items"][0]["id"], False)

    flat = _ctx_transcript(cid)
    assert "where's the key" in flat                  # restored alongside…
    assert "[Summary so far] SUMMARY-1" in flat        # …the summary
    assert "i lost it" not in flat                      # the others stay purged


# --- disabled plugin: action 409 -------------------------------------------

def test_disabled_plugin_action_409(client, ex):
    conv = store.create_conversation({
        "title": "Off", "counterpart_character_id": "mara-okafor",
        "config": {"enabled_plugins": []},
    })
    store.append_user_turn(conv["id"], [{"type": "dialogue", "text": "hi"}])
    r = _dispatch(client, conv["id"], {"mode": "keep", "detail": "standard"})
    assert r.status_code == 409


# --- mid-run executor failure surfaces, no chat system_error turn -----------

async def test_executor_failure_raises_no_error_turn(ex, monkeypatch):
    cid = _seed()

    async def boom(job_id, job_dir, request, event_bus=None):
        raise RuntimeError("llm exploded")

    monkeypatch.setattr(summarize, "execute_chain_job", boom)

    with pytest.raises(RuntimeError):
        await summ_plugin.run_summarize(cid, {"mode": "keep", "detail": "standard", "focus": ""})

    # No summary turn, and crucially no system_error chat turn was posted.
    transcript = store.get_transcript(cid)
    assert len(transcript["turns"]) == 3
    assert not any(it.get("type") in ("summary", "system_error")
                   for t in transcript["turns"] for it in t["items"])
