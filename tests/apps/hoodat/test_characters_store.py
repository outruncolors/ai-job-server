from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.apps.hoodat import characters_store as cs


def _fields(**over):
    base = {"name": "Ada", "occupation": "engineer", "appearance": {"hair": "red"}}
    base.update(over)
    return base


def test_create_assigns_server_fields_and_defaults():
    doc = cs.create_character(_fields())
    assert doc["id"] and doc["schema_version"] == 1
    assert doc["created_at"] and doc["updated_at"]
    assert doc["name"] == "Ada"
    assert doc["avatar_path"] is None
    # nested blocks default-filled
    assert doc["appearance"]["hair"] == "red"
    assert doc["personality"]["traits"] == []


def test_create_requires_name():
    with pytest.raises(ValidationError):
        cs.create_character({"occupation": "x"})


def test_get_list_delete():
    doc = cs.create_character(_fields())
    assert cs.get_character(doc["id"])["name"] == "Ada"
    assert any(d["id"] == doc["id"] for d in cs.list_characters())
    assert cs.delete_character(doc["id"]) is True
    assert cs.get_character(doc["id"]) is None
    assert cs.delete_character(doc["id"]) is False


def test_update_top_level_and_nested():
    doc = cs.create_character(_fields())
    updated = cs.update_character_fields(doc["id"], {
        "tagline": "the analyst",
        "appearance": {"primary_outfit": "tweed jacket"},
    })
    assert updated["tagline"] == "the analyst"
    assert updated["appearance"]["primary_outfit"] == "tweed jacket"
    # existing nested field preserved (deep-merge, not replace)
    assert updated["appearance"]["hair"] == "red"
    assert updated["updated_at"] >= doc["updated_at"]


def test_update_missing_returns_none():
    assert cs.update_character_fields("nope", {"tagline": "x"}) is None
