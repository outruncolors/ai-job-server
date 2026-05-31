"""Isolation for pack tests: point both pack trees and the wildcard store at tmp."""

from __future__ import annotations

import pytest

from app import wildcards as wildcards_mod
from app.packs import store as packs_store


@pytest.fixture(autouse=True)
def isolated_packs(tmp_path, monkeypatch):
    builtin = tmp_path / "packs"
    user = tmp_path / "config" / "packs"
    monkeypatch.setattr(packs_store, "BUILTIN_PACKS_DIR", builtin)
    monkeypatch.setattr(packs_store, "USER_PACKS_DIR", user)

    wc_dir = tmp_path / "config" / "wildcards"
    monkeypatch.setattr(wildcards_mod, "_DIR", wc_dir)
    monkeypatch.setattr(wildcards_mod, "_INDEX_PATH", wc_dir / "index.json")

    return {"builtin": builtin, "user": user}
