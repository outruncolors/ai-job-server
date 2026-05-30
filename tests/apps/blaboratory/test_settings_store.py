"""Operator-editable sim settings store (file overrides env defaults)."""

from __future__ import annotations

import json

import pytest

from app.apps.blaboratory import settings_store


@pytest.fixture
def settings_tmp(tmp_path, monkeypatch):
    """Isolate the settings file (repoint the import-time path constant)."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", path)
    return path


def test_defaults_when_no_file(settings_tmp):
    assert settings_store.get_settings() == dict(settings_store._DEFAULTS)
    assert not settings_tmp.exists()  # reading never writes


def test_update_persists_full_dict(settings_tmp):
    out = settings_store.update_settings({"tick_interval_seconds": 60})
    assert out["tick_interval_seconds"] == 60
    # untouched keys keep their defaults
    assert out["max_memory_items"] == settings_store._DEFAULTS["max_memory_items"]
    on_disk = json.loads(settings_tmp.read_text())
    assert on_disk["tick_interval_seconds"] == 60
    assert on_disk["max_memory_chars"] == settings_store._DEFAULTS["max_memory_chars"]


def test_partial_update_keeps_prior(settings_tmp):
    settings_store.update_settings({"tick_interval_seconds": 60})
    settings_store.update_settings({"max_memory_items": 5})
    s = settings_store.get_settings()
    assert s["tick_interval_seconds"] == 60  # survived the second update
    assert s["max_memory_items"] == 5


def test_getters_reflect_file(settings_tmp):
    settings_store.update_settings(
        {
            "tick_interval_seconds": 42,
            "max_memory_items": 7,
            "max_memory_chars": 999,
            "recency_floor_items": 3,
            "relevant_top_k": 4,
        }
    )
    assert settings_store.tick_interval_seconds() == 42
    assert settings_store.max_memory_items() == 7
    assert settings_store.max_memory_chars() == 999
    assert settings_store.recency_floor_items() == 3
    assert settings_store.relevant_top_k() == 4


def test_reject_non_int_and_writes_nothing(settings_tmp):
    with pytest.raises(settings_store.SettingsError) as exc:
        settings_store.update_settings({"tick_interval_seconds": "fast"})
    assert exc.value.field == "tick_interval_seconds"
    assert not settings_tmp.exists()


def test_reject_bool(settings_tmp):
    with pytest.raises(settings_store.SettingsError):
        settings_store.update_settings({"max_memory_items": True})


def test_reject_below_min(settings_tmp):
    with pytest.raises(settings_store.SettingsError) as exc:
        settings_store.update_settings({"tick_interval_seconds": 0})
    assert exc.value.field == "tick_interval_seconds"


def test_reject_above_max(settings_tmp):
    with pytest.raises(settings_store.SettingsError):
        settings_store.update_settings({"tick_interval_seconds": 999_999})


def test_reject_unknown_key(settings_tmp):
    with pytest.raises(settings_store.SettingsError) as exc:
        settings_store.update_settings({"bogus": 1})
    assert exc.value.field == "bogus"


def test_corrupt_file_falls_back_to_defaults(settings_tmp):
    settings_tmp.write_text("not json{", encoding="utf-8")
    assert settings_store.get_settings() == dict(settings_store._DEFAULTS)


def test_out_of_bounds_file_value_ignored(settings_tmp):
    # A value that slipped past validation (hand-edited file) is clamped to default.
    settings_tmp.write_text(json.dumps({"tick_interval_seconds": 10**9}), encoding="utf-8")
    assert (
        settings_store.get_settings()["tick_interval_seconds"]
        == settings_store._DEFAULTS["tick_interval_seconds"]
    )
