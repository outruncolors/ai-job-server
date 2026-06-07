"""The Prattletale message-shape wildcard: seed-if-absent + per-turn resolution
into the turn prompt. Store paths are monkeypatched to tmp."""

from __future__ import annotations

import pytest

from app import wildcards
from app.apps.prattletale import generator, seed
from app.apps.prattletale.seed import MESSAGE_STYLE_WILDCARD_NAME, seed_message_style_wildcard
from app.chain.models import ChainLLMConfig
from app.prompt_pal import store as pp_store


@pytest.fixture(autouse=True)
def _tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(wildcards, "_DIR", tmp_path / "wildcards")
    monkeypatch.setattr(wildcards, "_INDEX_PATH", tmp_path / "wildcards" / "index.json")
    # in-code prompt defaults (so the turn prompt carries the %% token)
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")


# ---- seeding ---------------------------------------------------------------

def test_seed_creates_the_wildcard_when_absent():
    assert seed_message_style_wildcard() is True
    names = [w["name"] for w in wildcards.list_wildcards()]
    assert MESSAGE_STYLE_WILDCARD_NAME in names

    wc = next(w for w in wildcards.list_wildcards() if w["name"] == MESSAGE_STYLE_WILDCARD_NAME)
    entries = wc["data"]["entries"]
    assert len(entries) == len(seed.MESSAGE_STYLE_ENTRIES)
    # the intended 40/30/20/10 distribution
    assert sorted((e["weight"] for e in entries), reverse=True) == [40, 30, 20, 10]


def test_seed_is_idempotent_and_does_not_clobber():
    seed_message_style_wildcard()
    # a user retunes the distribution
    wid = next(w["id"] for w in wildcards.list_wildcards() if w["name"] == MESSAGE_STYLE_WILDCARD_NAME)
    wildcards.update_wildcard(wid, MESSAGE_STYLE_WILDCARD_NAME, [{"text": "edited", "weight": 9}])

    assert seed_message_style_wildcard() is False  # already present -> no-op
    matching = [w for w in wildcards.list_wildcards() if w["name"] == MESSAGE_STYLE_WILDCARD_NAME]
    assert len(matching) == 1  # not duplicated
    assert matching[0]["data"]["entries"] == [{"text": "edited", "weight": 9}]  # edit preserved


# ---- generator resolves the token into the turn prompt ---------------------

def _ctx() -> dict:
    return {"character": "c", "scenario": "s", "role_instructions": "r",
            "user_persona": "p", "transcript": "[User] hi"}


def test_turn_prompt_has_the_token_then_generator_resolves_it():
    # the registered/seeded turn prompt carries the wildcard token
    raw = generator.get_text("prattletale", "turn", variables=_ctx())
    assert "%%Prattletale Message Style%%" in raw

    seed_message_style_wildcard()
    # The %%Prattletale Message Style%% wildcard lives in the single-prompt TURN;
    # in structured mode the director plan governs reply shape instead.
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"),
        structured_chat_history=False)
    turn_prompt = req.steps[0].alternatives[0].prompt

    # token is gone, replaced by one of the style directives
    assert "%%Prattletale Message Style%%" not in turn_prompt
    assert "%%" not in turn_prompt
    assert any(e["text"] in turn_prompt for e in seed.MESSAGE_STYLE_ENTRIES)


def test_token_left_literal_when_wildcard_absent():
    # if the wildcard hasn't been seeded, the token is left literal (no crash);
    # startup seeding is what guarantees presence in practice.
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"),
        structured_chat_history=False)
    assert "%%Prattletale Message Style%%" in req.steps[0].alternatives[0].prompt
