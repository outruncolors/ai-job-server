"""Hoodat characters carry an optional speaking_style.sfx block (round-trip +
back-compat for characters saved before the field existed)."""

from __future__ import annotations

from app.apps.hoodat import characters_store as cs


def test_sfx_field_roundtrip():
    char = cs.create_character({"name": "Ash"})
    updated = cs.update_character_fields(
        char["id"], {"speaking_style": {"sfx": {"emotes_identity": "young_woman",
                                                "enabled": True}}})
    sfx = updated["speaking_style"]["sfx"]
    assert sfx["emotes_identity"] == "young_woman" and sfx["enabled"] is True
    # survives a reload
    again = cs.get_character(char["id"])
    assert again["speaking_style"]["sfx"]["emotes_identity"] == "young_woman"


def test_missing_sfx_is_safe():
    char = cs.create_character({"name": "Bey"})
    assert (char.get("speaking_style") or {}).get("sfx") is None
