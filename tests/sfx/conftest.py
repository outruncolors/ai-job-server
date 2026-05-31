"""Shared fixtures for SFX tests: a tiny normalized pack tree under tmp_path."""

from __future__ import annotations

import json

import pytest


def _identity_manifest() -> dict:
    def item(iid, cat, desc):
        return {"id": iid, "category": cat, "description": desc, "tags": [cat],
                "path": f"normalized/test_emotes/files/{iid}.wav", "duration_ms": 800, "weight": 1.0}

    return {
        "schema_version": 1, "type": "sfx_pack", "id": "test_emotes",
        "binding": "identity", "display_name": "Test Emotes",
        "profiles": [
            {"id": "young_woman", "display_name": "Young Woman",
             "attributes": {"presentation": "female", "age_band": "young_adult", "pitch": "base"},
             "items": [item("yw_sneeze_01", "sneeze", "Sneeze"),
                       item("yw_sneeze_02", "sneeze", "Sneeze with gasp"),
                       item("yw_laugh_01", "laugh", "Soft laugh")]},
            {"id": "young_woman_high", "display_name": "Young Woman (high)",
             "attributes": {"presentation": "female", "age_band": "young_adult", "pitch": "high"},
             "items": [item("yw_sneeze_01_high", "sneeze", "Sneeze")]},
        ],
    }


def _global_manifest() -> dict:
    def item(iid, cat):
        return {"id": iid, "category": cat, "domain": "lewd", "description": cat,
                "tags": [cat, "lewd"], "path": f"normalized/test_lewd/files/{iid}.ogg",
                "duration_ms": 500, "weight": 1.0}

    return {
        "schema_version": 1, "type": "sfx_pack", "id": "test_lewd",
        "binding": "global", "domain": "lewd", "display_name": "Test Lewd",
        "profiles": [{"id": "_global", "display_name": "Global", "attributes": {},
                      "items": [item("lewd_wet_01", "wet"), item("lewd_wet_02", "wet")]}],
    }


@pytest.fixture()
def sfx_root(tmp_path, monkeypatch):
    """Point app.sfx.store at a tmp SFX_ROOT holding a 2-pack normalized tree."""
    import app.sfx.store as store

    root = tmp_path / "sfx"
    for pack_id, manifest in (("test_emotes", _identity_manifest()),
                              ("test_lewd", _global_manifest())):
        pack_dir = root / "normalized" / pack_id
        files = pack_dir / "files"
        files.mkdir(parents=True, exist_ok=True)
        (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for profile in manifest["profiles"]:
            for it in profile["items"]:
                (root / it["path"]).write_bytes(b"RIFF....fake")  # presence only
    monkeypatch.setattr(store, "SFX_ROOT", root)
    return root
