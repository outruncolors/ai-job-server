from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.apps.hoodat import characters_store as cs


def _fields(**over):
    base = {"name": "Ada", "occupation": "engineer", "appearance": {"hair_color": "red"}}
    base.update(over)
    return base


def test_create_assigns_server_fields_and_defaults():
    doc = cs.create_character(_fields())
    assert doc["id"] and doc["schema_version"] == 2
    assert doc["created_at"] and doc["updated_at"]
    assert doc["name"] == "Ada"
    assert doc["avatar_path"] is None
    # nested blocks default-filled
    assert doc["appearance"]["hair_color"] == "red"
    assert doc["appearance"]["outfits"] == []
    assert doc["experiences"] == []
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
        "appearance": {"skin": "tan"},
    })
    assert updated["tagline"] == "the analyst"
    assert updated["appearance"]["skin"] == "tan"
    # existing nested field preserved (deep-merge, not replace)
    assert updated["appearance"]["hair_color"] == "red"
    assert updated["updated_at"] >= doc["updated_at"]


def test_experiences_replaced_wholesale():
    doc = cs.create_character(_fields())
    a = cs.update_character_fields(doc["id"], {
        "experiences": [{"description": "won a prize", "valence": "positive"}],
    })
    assert a["experiences"] == [{"description": "won a prize", "valence": "positive"}]
    b = cs.update_character_fields(doc["id"], {"experiences": []})
    assert b["experiences"] == []


def test_outfits_replaced_wholesale_preserving_siblings():
    doc = cs.create_character(_fields())
    a = cs.update_character_fields(doc["id"], {
        "appearance": {"outfits": [{"name": "Casual", "top": "tee", "primary": True}]},
    })
    assert a["appearance"]["outfits"][0]["name"] == "Casual"
    # sibling appearance field survives the list patch (deep-merge)
    assert a["appearance"]["hair_color"] == "red"


def test_update_missing_returns_none():
    assert cs.update_character_fields("nope", {"tagline": "x"}) is None


def test_create_defaults_dialogue_examples_empty():
    doc = cs.create_character(_fields())
    assert doc["speaking_style"]["dialogue_examples"] == []


def test_dialogue_examples_replaced_wholesale():
    doc = cs.create_character(_fields(speaking_style={"description": "gruff"}))
    a = cs.update_character_fields(doc["id"], {"speaking_style": {"dialogue_examples": ["one", "two"]}})
    assert a["speaking_style"]["dialogue_examples"] == ["one", "two"]
    # a sibling field set earlier survives the list patch (deep-merge)
    assert a["speaking_style"]["description"] == "gruff"
    # a second patch replaces the list rather than appending/merging it
    b = cs.update_character_fields(doc["id"], {"speaking_style": {"dialogue_examples": ["three"]}})
    assert b["speaking_style"]["dialogue_examples"] == ["three"]
