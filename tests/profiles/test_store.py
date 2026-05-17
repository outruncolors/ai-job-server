from __future__ import annotations

import json

import pytest

from app import image_prompts as image_prompts_mod
from app import voice_presets as voice_presets_mod
from app import wildcards as wildcards_mod
from app.chain import context_library, sequences
from app.comfyui import config as comfyui_cfg
from app.omnivoice import config as omnivoice_cfg
from app.profiles import exporter, store


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    """Redirect both the live-config paths AND the profile store at tmp dirs."""
    cfg_root = tmp_path / "config"

    # Live-config paths the importer/exporter touch.
    llm_path = cfg_root / "llm_config.json"
    monkeypatch.setattr(exporter, "LLM_CONFIG_PATH", llm_path)
    import app.profiles.importer as imp
    monkeypatch.setattr(imp, "LLM_CONFIG_PATH", llm_path)

    monkeypatch.setattr(wildcards_mod, "_DIR", cfg_root / "wildcards")
    monkeypatch.setattr(wildcards_mod, "_INDEX_PATH", cfg_root / "wildcards" / "index.json")
    monkeypatch.setattr(context_library, "ITEMS_DIR", cfg_root / "context_items")
    monkeypatch.setattr(context_library, "INDEX_PATH", cfg_root / "context_items" / "index.json")
    monkeypatch.setattr(image_prompts_mod, "PROMPTS_DIR", cfg_root / "image_prompts")
    monkeypatch.setattr(image_prompts_mod, "INDEX_PATH", cfg_root / "image_prompts" / "index.json")
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", cfg_root / "chain_sequences")
    monkeypatch.setattr(sequences, "INDEX_PATH", cfg_root / "chain_sequences" / "index.json")

    # Profile store layout.
    profiles_dir = cfg_root / "profiles"
    monkeypatch.setattr(store, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(store, "INDEX_PATH", profiles_dir / "index.json")
    monkeypatch.setattr(store, "ACTIVE_PATH", profiles_dir / "active.json")

    return cfg_root


def _seed_live_config_v1():
    """First state: speed=1.1, one image prompt 'alpha', one wildcard 'one'."""
    omnivoice_cfg.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    omnivoice_cfg.CONFIG_PATH.write_text(json.dumps({"speed": 1.1}), encoding="utf-8")
    omnivoice_cfg._config = None
    image_prompts_mod.create_prompt("alpha", "moody")
    wildcards_mod.create_wildcard("one", [{"text": "uno"}])


def _seed_live_config_v2():
    """Second state: speed=1.7, image prompt 'beta', wildcard 'two'."""
    omnivoice_cfg.CONFIG_PATH.write_text(json.dumps({"speed": 1.7}), encoding="utf-8")
    omnivoice_cfg._config = None
    image_prompts_mod.create_prompt("beta", "vivid")
    wildcards_mod.create_wildcard("two", [{"text": "dos"}])


def test_save_then_list_then_get(isolated_profiles):
    _seed_live_config_v1()
    entry = store.save_profile("v1", description="initial state")

    assert entry["id"]
    assert entry["name"] == "v1"
    assert entry["description"] == "initial state"

    listed = store.list_profiles()
    assert [e["id"] for e in listed] == [entry["id"]]
    assert store.get_profile(entry["id"]) == entry
    assert store.get_profile("nope") is None

    # On-disk layout exists.
    profile_dir = store.PROFILES_DIR / entry["id"]
    assert (profile_dir / "master.json").exists()
    assert (profile_dir / "assets" / "voice_presets").is_dir()


def test_save_preserves_voice_wav_bytes(isolated_profiles):
    voice_presets_mod.save_preset("Narrator", "warm", b"WAV-BYTES")
    entry = store.save_profile("with-voice")
    wavs = list((store.PROFILES_DIR / entry["id"] / "assets" / "voice_presets").iterdir())
    assert len(wavs) == 1
    assert wavs[0].read_bytes() == b"WAV-BYTES"


def test_set_active_switches_a_sample_domain(isolated_profiles):
    # Save v1 snapshot.
    _seed_live_config_v1()
    v1 = store.save_profile("v1")

    # Mutate live config to v2 and save another snapshot.
    _seed_live_config_v2()
    v2 = store.save_profile("v2")

    # Sanity: live config currently matches v2.
    assert omnivoice_cfg.get_config().speed == 1.7
    assert sorted(p["name"] for p in image_prompts_mod.list_prompts()) == ["alpha", "beta"]
    assert sorted(w["name"] for w in wildcards_mod.list_wildcards()) == ["one", "two"]

    # Switch back to v1 — live state should snap back.
    report = store.set_active(v1["id"])
    assert report.mode == "replace"
    assert store.get_active_id() == v1["id"]
    assert store.get_active()["id"] == v1["id"]

    omnivoice_cfg._config = None
    assert omnivoice_cfg.get_config().speed == 1.1
    assert [p["name"] for p in image_prompts_mod.list_prompts()] == ["alpha"]
    assert [w["name"] for w in wildcards_mod.list_wildcards()] == ["one"]

    # And forward to v2.
    store.set_active(v2["id"])
    omnivoice_cfg._config = None
    assert omnivoice_cfg.get_config().speed == 1.7
    assert sorted(p["name"] for p in image_prompts_mod.list_prompts()) == ["alpha", "beta"]


def test_set_active_unknown_id_raises(isolated_profiles):
    with pytest.raises(FileNotFoundError):
        store.set_active("does-not-exist")


def test_delete_clears_active_when_target_was_active(isolated_profiles):
    _seed_live_config_v1()
    v1 = store.save_profile("v1")
    store.set_active(v1["id"])
    assert store.get_active_id() == v1["id"]

    assert store.delete_profile(v1["id"]) is True
    assert store.get_active_id() is None
    assert store.list_profiles() == []
    assert not (store.PROFILES_DIR / v1["id"]).exists()


def test_delete_keeps_active_when_other_was_active(isolated_profiles):
    _seed_live_config_v1()
    v1 = store.save_profile("v1")
    _seed_live_config_v2()
    v2 = store.save_profile("v2")
    store.set_active(v2["id"])

    assert store.delete_profile(v1["id"]) is True
    assert store.get_active_id() == v2["id"]


def test_delete_unknown_returns_false(isolated_profiles):
    assert store.delete_profile("ghost") is False


def test_save_uniques_duplicate_names(isolated_profiles):
    a = store.save_profile("snap")
    b = store.save_profile("snap")
    assert a["name"] == "snap"
    assert b["name"] == "snap (2)"


def test_save_rejects_blank_name(isolated_profiles):
    with pytest.raises(ValueError):
        store.save_profile("   ")


def test_get_active_returns_none_when_unset(isolated_profiles):
    assert store.get_active_id() is None
    assert store.get_active() is None
