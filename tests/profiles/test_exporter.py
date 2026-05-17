from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import image_prompts as image_prompts_mod
from app import voice_presets as voice_presets_mod
from app import wildcards as wildcards_mod
from app.chain import context_library, sequences
from app.comfyui import config as comfyui_cfg
from app.omnivoice import config as omnivoice_cfg
from app.profiles import exporter
from app.profiles.exporter import build_master_profile, list_required_assets
from app.profiles.models import MasterProfile


@pytest.fixture
def seeded_config(tmp_path, monkeypatch):
    """Point every domain at tmp_path and seed each with one realistic entry."""
    cfg_root = tmp_path / "config"
    cfg_root.mkdir()

    # --- llm_config -------------------------------------------------
    llm_path = cfg_root / "llm_config.json"
    llm_path.write_text(
        json.dumps(
            {
                "presets": [
                    {
                        "id": "llm-1",
                        "name": "local-gemma",
                        "api_base": "http://127.0.0.1:8080/v1",
                        "model": "gemma-3-27b",
                        "temperature": 0.4,
                        "max_tokens": 4096,
                        "timeout_seconds": 60,
                    }
                ],
                "default_preset_id": "llm-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(exporter, "LLM_CONFIG_PATH", llm_path)

    # --- omnivoice (conftest already patches CONFIG_PATH to a tmp dir) ----
    omnivoice_cfg.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    omnivoice_cfg.CONFIG_PATH.write_text(
        json.dumps({"model": "k2-fsa/OmniVoice", "voice": "default", "speed": 1.2}),
        encoding="utf-8",
    )
    omnivoice_cfg._config = None

    # --- comfyui (conftest patches CONFIG_PATH + WORKFLOWS_DIR) -----------
    comfyui_cfg.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    comfyui_cfg.CONFIG_PATH.write_text(
        json.dumps({"port": 8188, "default_workflow": "flux-dev.json"}),
        encoding="utf-8",
    )
    comfyui_cfg._config = None
    comfyui_cfg.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    (comfyui_cfg.WORKFLOWS_DIR / "flux-dev.json").write_text(
        json.dumps({"1": {"class_type": "KSampler", "inputs": {"steps": 20}}}),
        encoding="utf-8",
    )

    # --- voice_presets (conftest patches PRESETS_DIR + INDEX_PATH) --------
    voice_presets_mod.save_preset("Narrator", "warm, mid-range", b"RIFFfake")

    # --- wildcards --------------------------------------------------------
    wcdir = cfg_root / "wildcards"
    monkeypatch.setattr(wildcards_mod, "_DIR", wcdir)
    monkeypatch.setattr(wildcards_mod, "_INDEX_PATH", wcdir / "index.json")
    wildcards_mod.create_wildcard("color", [{"text": "red"}, {"text": "blue"}], "basic palette")

    # --- context_items ----------------------------------------------------
    ctxdir = cfg_root / "context_items"
    monkeypatch.setattr(context_library, "ITEMS_DIR", ctxdir)
    monkeypatch.setattr(context_library, "INDEX_PATH", ctxdir / "index.json")
    context_library.create_item(
        "House style", ["style"], "Tone guide", "Write tight."
    )

    # --- image_prompts ----------------------------------------------------
    ipdir = cfg_root / "image_prompts"
    monkeypatch.setattr(image_prompts_mod, "PROMPTS_DIR", ipdir)
    monkeypatch.setattr(image_prompts_mod, "INDEX_PATH", ipdir / "index.json")
    image_prompts_mod.create_prompt("moody portrait", "cinematic, %%color%% lighting", "flux-dev.json")

    # --- chain_sequences --------------------------------------------------
    seqdir = cfg_root / "chain_sequences"
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", seqdir)
    monkeypatch.setattr(sequences, "INDEX_PATH", seqdir / "index.json")
    sequences.save_sequence(
        "story-then-voice",
        [
            {"id": "a", "name": "Draft", "type": "llm", "prompt": "Write a scene"},
            {"id": "b", "name": "Read", "type": "voice"},
        ],
    )

    return cfg_root


def test_build_master_profile_populates_every_domain(seeded_config):
    profile = build_master_profile("snapshot-1", description="initial export")

    assert profile.name == "snapshot-1"
    assert profile.description == "initial export"
    assert profile.created_at  # auto-set

    # Every domain non-empty.
    assert len(profile.llm_config.presets) == 1
    assert profile.llm_config.default_preset_id == "llm-1"

    assert profile.omnivoice.speed == 1.2
    assert profile.comfyui.default_workflow == "flux-dev.json"
    assert "flux-dev.json" in profile.comfyui_workflows
    assert profile.comfyui_workflows["flux-dev.json"]["1"]["class_type"] == "KSampler"

    assert len(profile.voice_presets) == 1
    assert profile.voice_presets[0].name == "Narrator"
    assert profile.voice_presets[0].wav_filename.endswith(".wav")

    assert [w.name for w in profile.wildcards] == ["color"]
    assert [c.title for c in profile.context_items] == ["House style"]
    assert [p.name for p in profile.image_prompts] == ["moody portrait"]
    assert [s.name for s in profile.chain_sequences] == ["story-then-voice"]

    # Asset manifest mirrors the voice presets.
    assert len(profile.asset_manifest) == 1
    assert profile.asset_manifest[0].kind == "voice_wav"
    assert profile.asset_manifest[0].filename == profile.voice_presets[0].wav_filename


def test_built_profile_round_trips_through_validation(seeded_config):
    profile = build_master_profile("snapshot-1")
    payload = profile.model_dump_json()
    restored = MasterProfile.model_validate_json(payload)
    assert restored.model_dump() == profile.model_dump()


def test_list_required_assets_returns_existing_wav_paths(seeded_config):
    profile = build_master_profile("snapshot-1")
    paths = list_required_assets(profile)
    assert len(paths) == 1
    assert isinstance(paths[0], Path)
    assert paths[0].is_absolute()
    assert paths[0].exists()
    assert paths[0].read_bytes() == b"RIFFfake"


def test_build_with_empty_config_dirs(tmp_path, monkeypatch):
    """No seeded data — profile should still validate, all collections empty."""
    monkeypatch.setattr(exporter, "LLM_CONFIG_PATH", tmp_path / "missing-llm.json")
    # conftest already points omnivoice/comfyui/voice_presets at tmp.
    # Point the rest at fresh tmp dirs too.
    monkeypatch.setattr(wildcards_mod, "_DIR", tmp_path / "wc")
    monkeypatch.setattr(wildcards_mod, "_INDEX_PATH", tmp_path / "wc" / "index.json")
    monkeypatch.setattr(context_library, "ITEMS_DIR", tmp_path / "ctx")
    monkeypatch.setattr(context_library, "INDEX_PATH", tmp_path / "ctx" / "index.json")
    monkeypatch.setattr(image_prompts_mod, "PROMPTS_DIR", tmp_path / "ip")
    monkeypatch.setattr(image_prompts_mod, "INDEX_PATH", tmp_path / "ip" / "index.json")
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", tmp_path / "seq")
    monkeypatch.setattr(sequences, "INDEX_PATH", tmp_path / "seq" / "index.json")

    profile = build_master_profile("blank")
    assert profile.llm_config.presets == []
    assert profile.comfyui_workflows == {}
    assert profile.voice_presets == []
    assert profile.wildcards == []
    assert profile.context_items == []
    assert profile.image_prompts == []
    assert profile.chain_sequences == []
    assert profile.asset_manifest == []
    assert list_required_assets(profile) == []
