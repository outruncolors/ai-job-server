"""Phase 1 — lenient structured JSON parsing (chain/structured.py)."""

from __future__ import annotations

from app.chain.structured import parse_json_output


def test_clean_json():
    obj, err = parse_json_output('{"a": 1, "b": [2, 3]}')
    assert err is None
    assert obj == {"a": 1, "b": [2, 3]}


def test_fenced_json():
    raw = "Here is the result:\n```json\n{\"name\": \"mara\"}\n```\nDone."
    obj, err = parse_json_output(raw)
    assert err is None
    assert obj == {"name": "mara"}


def test_json_with_prose_around_it():
    raw = 'Sure! {"ok": true, "items": ["x"]} hope that helps'
    obj, err = parse_json_output(raw)
    assert err is None
    assert obj == {"ok": True, "items": ["x"]}


def test_array_top_level():
    obj, err = parse_json_output("[1, 2, 3]")
    assert err is None
    assert obj == [1, 2, 3]


def test_braces_inside_strings_dont_break_extraction():
    raw = 'noise {"text": "a } b { c"} tail'
    obj, err = parse_json_output(raw)
    assert err is None
    assert obj == {"text": "a } b { c"}


def test_empty_returns_error():
    obj, err = parse_json_output("   ")
    assert obj is None
    assert err


def test_garbage_returns_error():
    obj, err = parse_json_output("this is not json at all")
    assert obj is None
    assert err


def test_schema_shape_check_object():
    obj, err = parse_json_output('["not", "an", "object"]', {"type": "object"})
    assert obj is None
    assert "expected object" in err


def test_schema_required_keys():
    obj, err = parse_json_output(
        '{"title": "x"}', {"type": "object", "required": ["title", "body"]}
    )
    assert obj is None
    assert "body" in err


def test_schema_passes_when_satisfied():
    obj, err = parse_json_output(
        '{"title": "x", "body": "y"}', {"type": "object", "required": ["title", "body"]}
    )
    assert err is None
    assert obj == {"title": "x", "body": "y"}
