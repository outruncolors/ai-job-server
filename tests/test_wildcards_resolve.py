"""Server-side wildcard resolution (``app.wildcards.resolve_wildcards``).

The frontend resolves ``%%name%%`` before sending a prompt; this is the
server-side equivalent used by prompts built in Python (e.g. Prattletale's turn
prompt). Monkeypatches the store paths to tmp so nothing touches real config.
"""

from __future__ import annotations

import random

import pytest

from app import wildcards


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(wildcards, "_DIR", tmp_path / "wildcards")
    monkeypatch.setattr(wildcards, "_INDEX_PATH", tmp_path / "wildcards" / "index.json")


def test_resolves_a_known_token_to_its_only_entry():
    wildcards.create_wildcard("Mood", [{"text": "grumpy", "weight": 5}])
    assert wildcards.resolve_wildcards("she is %%Mood%% today") == "she is grumpy today"


def test_unknown_token_is_left_literal():
    assert wildcards.resolve_wildcards("hi %%NoSuchThing%%") == "hi %%NoSuchThing%%"


def test_no_tokens_passthrough():
    assert wildcards.resolve_wildcards("plain text") == "plain text"
    assert wildcards.resolve_wildcards("") == ""


def test_name_match_is_case_insensitive():
    wildcards.create_wildcard("Greeting", [{"text": "hey"}])
    assert wildcards.resolve_wildcards("%%greeting%%") == "hey"


def test_nested_tokens_resolve_recursively():
    wildcards.create_wildcard("Inner", [{"text": "world"}])
    wildcards.create_wildcard("Outer", [{"text": "hello %%Inner%%"}])
    assert wildcards.resolve_wildcards("%%Outer%%") == "hello world"


def test_cycle_is_left_literal_not_infinite():
    # create_wildcard's own cycle check rejects a true cycle, so build one by
    # editing entries directly past the guard via the index.
    wildcards.create_wildcard("A", [{"text": "a then %%B%%"}])
    wildcards.create_wildcard("B", [{"text": "b"}])
    # now make B point back at A on disk (bypassing the save-time cycle check)
    items = wildcards.list_wildcards()
    for it in items:
        if it["name"] == "B":
            it["data"]["entries"] = [{"text": "b then %%A%%"}]
    wildcards._write_index(items)
    out = wildcards.resolve_wildcards("%%A%%")
    # resolves until it would revisit A, then leaves that token literal
    assert out.startswith("a then b then")
    assert "%%A%%" in out


def test_brace_wc_cross_refs_are_cycle_checked_on_save():
    # Post-migration entries cross-reference via {{wc.name}}; cycle detection must
    # see that spelling too (app.wildcards._extract_refs recognizes both).
    wildcards.create_wildcard("A", [{"text": "go {{wc.B}}"}])
    with pytest.raises(ValueError, match="Cycle"):
        wildcards.create_wildcard("B", [{"text": "back {{wc.A}}"}])


def test_weight_dominates_selection():
    wildcards.create_wildcard("Pick", [
        {"text": "rare", "weight": 1},
        {"text": "common", "weight": 1000},
    ])
    random.seed(1234)
    picks = [wildcards.resolve_wildcards("%%Pick%%") for _ in range(200)]
    assert picks.count("common") > 180  # ~1000:1 odds


def test_zero_or_missing_weight_defaults_like_frontend():
    # weight 0 / missing both behave as 5 (matches JS `e.weight || 5`); with equal
    # effective weights both texts should appear across draws.
    wildcards.create_wildcard("Even", [{"text": "x", "weight": 0}, {"text": "y"}])
    random.seed(7)
    seen = {wildcards.resolve_wildcards("%%Even%%") for _ in range(50)}
    assert seen == {"x", "y"}
