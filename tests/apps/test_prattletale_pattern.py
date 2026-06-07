"""Recent-pattern analysis — pure helpers feeding the director prompt."""

from __future__ import annotations

from app.apps.prattletale import generator


def _model_turn(*dialogue: str, extra_items: int = 0) -> dict:
    items = [{"type": "dialogue", "text": d} for d in dialogue]
    items += [{"type": "action", "text": "shrugs"} for _ in range(extra_items)]
    return {"author": "model", "items": items}


def _user_turn(text: str) -> dict:
    return {"author": "user", "items": [{"type": "dialogue", "text": text}]}


def test_summary_collects_openings_counts_and_question():
    transcript = {"turns": [
        _user_turn("hey"),
        _model_turn("yeah i guess so"),
        _user_turn("really"),
        _model_turn("yeah well whatever", extra_items=1),
        _user_turn("hm"),
        _model_turn("do you think so?"),
    ]}
    s = generator.build_recent_pattern_summary(transcript, {})
    # Leading openers are skipped, then the next 3 words are kept verbatim. None of
    # these lines start with a trivial opener, so all keep their first 3 words.
    assert s["recent_openings"] == ["yeah i guess", "yeah well whatever", "do you think"]
    # counts: 1 dialogue, 1 dialogue + 1 action = 2, 1 dialogue.
    assert s["recent_message_counts"] == [1, 2, 1]
    assert s["last_model_ended_with_question"] is True


def test_summary_detects_overused_phrases():
    transcript = {"turns": [
        _model_turn("i mean it's fine"),
        _model_turn("i mean whatever"),
        _model_turn("i mean sure"),
    ]}
    s = generator.build_recent_pattern_summary(transcript, {})
    assert "i mean" in s["overused_phrases"]


def test_summary_ignores_non_model_and_hidden():
    transcript = {"turns": [
        _user_turn("question one?"),
        {"author": "model", "items": [
            {"type": "dialogue", "text": "secret", "hidden_from_context": True},
        ]},
    ]}
    s = generator.build_recent_pattern_summary(transcript, {})
    assert s["recent_openings"] == []
    # The user turn ending in '?' must NOT set the model-question flag.
    assert s["last_model_ended_with_question"] is False


def test_render_block_vanishes_when_empty():
    assert generator.render_pattern_block(generator.build_recent_pattern_summary({"turns": []}, {})) == ""


def test_render_block_mentions_repeats():
    transcript = {"turns": [
        _model_turn("so anyway it goes"),
        _model_turn("so anyway whatever"),
        _model_turn("right?"),
    ]}
    block = generator.render_pattern_block(generator.build_recent_pattern_summary(transcript, {}))
    assert "RECENT PATTERN" in block
    assert "so anyway" in block
    assert "ended on a question" in block


def test_build_context_carries_pattern_block_string():
    conv = {"config": {}, "device_user": {}, "scenario": "", "role_instructions": ""}
    transcript = {"turns": [_model_turn("yeah ok sure"), _model_turn("yeah ok fine")]}
    ctx = generator.build_context(conv, {"name": "C"}, transcript)
    # build_context returns only strings (the bundle is passed as get_text vars).
    assert isinstance(ctx["_pattern_block"], str)
    assert all(isinstance(v, str) for v in ctx.values())
    assert "RECENT PATTERN" in ctx["_pattern_block"]  # repeated openings present
