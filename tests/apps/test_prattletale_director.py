"""Director plan parsing + rendering (app/apps/prattletale/director.py)."""

from __future__ import annotations

from app.apps.prattletale.director import parse_director_plan, render_director_plan


def test_parse_clean_json():
    plan = parse_director_plan(
        '{"reply_shape": {"message_count": 2, "include_action": true, '
        '"include_narration": false}, "conversation_move": "tease", '
        '"emotional_temperature": "playful", "stance": "coy", '
        '"must_reference": "their excuse", "must_include": "a callback", '
        '"must_avoid": ["another question"], "length": "short"}'
    )
    assert plan is not None
    assert plan["reply_shape"] == {
        "message_count": 2, "include_action": True, "include_narration": False,
    }
    assert plan["conversation_move"] == "tease"
    assert plan["must_avoid"] == ["another question"]


def test_parse_strips_fences_and_prose():
    plan = parse_director_plan(
        "Here's the plan:\n```json\n"
        '{"conversation_move": "push back", "length": "terse"}\n'
        "```\nhope that helps"
    )
    assert plan is not None
    assert plan["conversation_move"] == "push back"
    assert plan["length"] == "terse"


def test_parse_handles_brace_inside_string():
    plan = parse_director_plan('{"conversation_move": "say {weird}", "length": "short"}')
    assert plan is not None
    assert plan["conversation_move"] == "say {weird}"


def test_parse_clamps_and_coerces():
    plan = parse_director_plan(
        '{"reply_shape": {"message_count": 99}, "length": "epic", '
        '"must_avoid": "single string", "conversation_move": "x"}'
    )
    assert plan is not None
    assert plan["reply_shape"]["message_count"] == 4  # clamped to 1..4
    assert plan["length"] == "short"  # invalid -> default
    assert plan["must_avoid"] == ["single string"]  # scalar -> list


def test_parse_none_on_garbage():
    assert parse_director_plan("no json here") is None
    assert parse_director_plan("") is None
    assert parse_director_plan("[1, 2, 3]") is None  # not an object


def test_parse_none_on_empty_directives():
    # Valid JSON but no actual directive content -> None so the caller falls back.
    assert parse_director_plan('{"reply_shape": {"message_count": 1}}') is None


def test_render_block_includes_directives():
    plan = parse_director_plan(
        '{"reply_shape": {"message_count": 2, "include_action": true}, '
        '"conversation_move": "tease", "emotional_temperature": "warm", '
        '"must_avoid": ["a", "b"], "length": "short"}'
    )
    block = render_director_plan(plan)
    assert "PLAN FOR THIS REPLY" in block
    assert "Send 2 message(s)" in block
    assert "Include an action beat: yes" in block
    assert "Conversational move: tease" in block
    assert "Do NOT do any of these: a; b" in block


def test_render_empty_for_falsy_plan():
    assert render_director_plan(None) == ""
    assert render_director_plan({}) == ""
