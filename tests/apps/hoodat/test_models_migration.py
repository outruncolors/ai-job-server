"""v1 -> v2 Appearance migration: legacy `hair`/`eyes`/`primary_outfit` are
hoisted into the new shape by the `Appearance` before-validator, and the store
normalizes legacy docs on read."""
from __future__ import annotations

import json

from app.apps.hoodat import characters_store as cs
from app.apps.hoodat.models import Character

_LEGACY = {
    "id": "11111111-1111-1111-1111-111111111111",
    "schema_version": 1,
    "created_at": "2024-01-01T00:00:00+00:00",
    "updated_at": "2024-01-01T00:00:00+00:00",
    "name": "Legacy Lou",
    "appearance": {
        "height": "5'10\"",
        "hair": "honey-blonde ponytail",
        "eyes": "emerald green",
        "skin": "tan",
        "distinguishing_features": ["freckles"],
        "primary_outfit": "pink tube top and jean shorts",
    },
}


def test_model_migrates_legacy_appearance():
    # Drop schema_version (Literal[2] rejects 1); the validator does the rest.
    doc = {k: v for k, v in _LEGACY.items() if k != "schema_version"}
    c = Character(**doc).model_dump()
    app = c["appearance"]
    assert app["hair_color"] == "honey-blonde ponytail"
    assert app["hair_details"] == ""
    assert app["eye_color"] == "emerald green"
    assert app["outfits"] == [
        {"name": "Primary", "top": "pink tube top and jean shorts", "bottoms": "",
         "underwear": "", "socks_shoes": "", "accessories": "", "primary": True}
    ]
    assert c["schema_version"] == 2
    assert c["experiences"] == []
    # legacy keys do not survive
    for legacy in ("hair", "eyes", "primary_outfit"):
        assert legacy not in app


def test_get_character_normalizes_legacy_file_on_read(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CHARACTERS_DIR", tmp_path)
    (tmp_path / f"{_LEGACY['id']}.json").write_text(json.dumps(_LEGACY), encoding="utf-8")

    got = cs.get_character(_LEGACY["id"])
    assert got["schema_version"] == 2
    assert got["appearance"]["hair_color"] == "honey-blonde ponytail"
    assert got["appearance"]["outfits"][0]["top"] == "pink tube top and jean shorts"
    assert "hair" not in got["appearance"]
    # listing normalizes too
    listed = cs.list_characters()
    assert listed and listed[0]["appearance"]["eye_color"] == "emerald green"


def test_migration_does_not_clobber_existing_v2_values():
    doc = {
        "id": "x", "created_at": "t", "updated_at": "t", "name": "N",
        "appearance": {"hair": "old", "hair_color": "new"},
    }
    app = Character(**doc).model_dump()["appearance"]
    assert app["hair_color"] == "new"  # explicit v2 value wins over legacy
    assert "hair" not in app
