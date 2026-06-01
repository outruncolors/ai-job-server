"""SP2 — Prattletale prompt registration + canonical-message parser (no network)."""

from __future__ import annotations

import pytest

from app.apps.prattletale.prompts import (
    GenerationError,
    _strip_fences,
    parse_items,
)
from app.prompt_pal import registry, service, store


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")


# ---- registration / seeding ------------------------------------------------

def test_turn_prompt_seeds_and_composes_with_variables():
    registry.seed_registered()

    entry = store.get_by_app_key("prattletale", "turn")
    assert entry is not None
    assert entry["data"]["guard"] is not None

    text = service.get_text(
        "prattletale",
        "turn",
        variables={
            "character": "Name: Mara",
            "scenario": "1am diner",
            "role_instructions": "Stay in character.",
            "user_persona": "A tired regular.",
            "transcript": "[User] you actually showed up",
        },
    )
    # Provided variables are substituted; the format instruction survives.
    assert "Name: Mara" in text
    assert "1am diner" in text
    assert "[User] you actually showed up" in text
    assert "[say]" in text and "[feel]" in text
    # Chain tokens / unrelated vars are not introduced.
    assert "{{var.character}}" not in text


def test_get_guard_returns_hygiene_pass():
    registry.seed_registered()
    guard = service.get_guard("prattletale", "turn")
    assert guard is not None
    # The guard runs over the first step's output via the chain token.
    assert "{{previous}}" in guard
    assert "FORMAT HYGIENE" in guard
    # The guard also scrubs emoji (belt-and-suspenders with the parser).
    assert "emoji" in guard.lower()


def test_variety_prompt_seeds_and_composes_with_transcript():
    registry.seed_registered()
    entry = store.get_by_app_key("prattletale", "variety")
    assert entry is not None

    text = service.get_text(
        "prattletale", "variety",
        variables={"character": "Name: Mara", "transcript": "[Mara] same opening again"},
    )
    # The recent conversation is baked in; the draft token is left for the executor.
    assert "[Mara] same opening again" in text
    assert "{{previous}}" in text
    assert "{{var.transcript}}" not in text


# ---- parser: canonical message format --------------------------------------

def test_quoted_line_parses_as_dialogue():
    assert parse_items('"hello"') == [{"type": "dialogue", "text": "hello"}]


def test_dialogue_keeps_nested_single_quotes():
    items = parse_items('"Did you just say \'maskidate\'?"')
    assert items == [{"type": "dialogue", "text": "Did you just say 'maskidate'?"}]


def test_asterisk_line_parses_as_action():
    assert parse_items("*Mara looks away.*") == [{"type": "action", "text": "Mara looks away."}]


def test_plain_line_parses_as_narration():
    assert parse_items("The room goes quiet.") == [
        {"type": "narration", "text": "The room goes quiet."}
    ]


def test_multiple_action_spans_split_into_separate_items():
    # Each *…* span is its own action item -> its own SFX candidate.
    items = parse_items("*turns around* *opens the door*")
    assert items == [
        {"type": "action", "text": "turns around"},
        {"type": "action", "text": "opens the door"},
    ]


def test_underscore_wrapped_line_normalized_to_narration():
    assert parse_items("_she hesitates_") == [{"type": "narration", "text": "she hesitates"}]


def test_canonical_mix_parses_in_order():
    raw = '*She slides the menu across the table.*\n"Where else would I be."\nRain streaks the window.'
    items = parse_items(raw)
    assert [it["type"] for it in items] == ["action", "dialogue", "narration"]


# ---- parser: legacy bracket tags (back-compat input only) ------------------

def test_legacy_tags_map_to_item_types():
    raw = (
        "[say] hello\n"
        "[do] turns around\n"
        "[narration] The room goes quiet.\n"
        "[feel] nervous"
    )
    items = parse_items(raw)
    # [feel] collapses into narration — the canonical format has no feeling type.
    assert [it["type"] for it in items] == ["dialogue", "action", "narration", "narration"]
    assert items[0]["text"] == "hello"
    assert items[1]["text"] == "turns around"


def test_fences_are_stripped():
    raw = '```\n"hi"\nshe waves.\n```'
    items = parse_items(raw)
    assert [it["type"] for it in items] == ["dialogue", "narration"]
    assert items[0]["text"] == "hi"


def test_language_hinted_fence_is_stripped():
    assert _strip_fences('```text\n"hi"\n```') == '"hi"'


def test_unknown_tag_maps_to_narration():
    items = parse_items("[bogus] some scene beat")
    assert items == [{"type": "narration", "text": "some scene beat"}]


@pytest.mark.parametrize("raw", ["", "   ", "\n\n  \t\n", "```\n\n```"])
def test_empty_or_whitespace_raises(raw):
    with pytest.raises(GenerationError):
        parse_items(raw)


# ---- emoji scrub -----------------------------------------------------------

def test_emoji_are_stripped_from_items():
    raw = "[say] hey there 😊👋\n[narration] she waves 🎉"
    items = parse_items(raw)
    assert items[0]["text"] == "hey there"
    assert items[1]["text"] == "she waves"


def test_emoji_with_zwj_and_skin_tone_are_stripped():
    raw = "[say] family time 👨‍👩‍👧 and a thumbs up 👍🏽"
    items = parse_items(raw)
    assert items[0]["text"] == "family time and a thumbs up"


def test_item_emptied_by_emoji_scrub_is_dropped():
    raw = "[say] 🙂\n[say] still here"
    items = parse_items(raw)
    assert [i["text"] for i in items] == ["still here"]


def test_all_emoji_output_raises():
    with pytest.raises(GenerationError):
        parse_items("[say] 😀😀\n[say] 🎉")
