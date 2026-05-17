from __future__ import annotations

import json

import pytest

from app import image_prompts as image_prompts_mod
from app import voice_presets as voice_presets_mod
from app import wildcards as wildcards_mod
from app.chain import context_library, sequences
from app.comfyui import config as comfyui_cfg
from app.omnivoice import config as omnivoice_cfg
from app.profiles import importer
from app.profiles.importer import apply_master_profile
from app.profiles.models import (
    ChainSequenceEntry,
    ContextItemEntry,
    ImagePromptEntry,
    MasterProfile,
    ProfileAsset,
    VoicePresetEntry,
    WildcardEntry,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point every domain at fresh tmp dirs (conftest covers a few; cover the rest)."""
    cfg_root = tmp_path / "config"

    llm_path = cfg_root / "llm_config.json"
    monkeypatch.setattr(importer, "LLM_CONFIG_PATH", llm_path)

    monkeypatch.setattr(wildcards_mod, "_DIR", cfg_root / "wildcards")
    monkeypatch.setattr(wildcards_mod, "_INDEX_PATH", cfg_root / "wildcards" / "index.json")

    monkeypatch.setattr(context_library, "ITEMS_DIR", cfg_root / "context_items")
    monkeypatch.setattr(context_library, "INDEX_PATH", cfg_root / "context_items" / "index.json")

    monkeypatch.setattr(image_prompts_mod, "PROMPTS_DIR", cfg_root / "image_prompts")
    monkeypatch.setattr(image_prompts_mod, "INDEX_PATH", cfg_root / "image_prompts" / "index.json")

    monkeypatch.setattr(sequences, "SEQUENCES_DIR", cfg_root / "chain_sequences")
    monkeypatch.setattr(sequences, "INDEX_PATH", cfg_root / "chain_sequences" / "index.json")

    return cfg_root


def _profile_with_payload(asset_filename: str = "vp1.wav") -> MasterProfile:
    return MasterProfile(
        name="snapshot",
        llm_config={
            "presets": [
                {
                    "id": "llm-1",
                    "name": "remote",
                    "api_base": "http://example/v1",
                    "model": "x",
                    "temperature": 0.5,
                    "max_tokens": 1024,
                    "timeout_seconds": 30,
                }
            ],
            "default_preset_id": "llm-1",
        },
        omnivoice={"speed": 1.3},
        comfyui={"port": 8188, "default_workflow": "flux-dev.json"},
        comfyui_workflows={
            "flux-dev.json": {"1": {"class_type": "KSampler", "inputs": {"steps": 22}}}
        },
        voice_presets=[
            VoicePresetEntry(id="vp1", name="Narrator", caption="warm", wav_filename=asset_filename)
        ],
        wildcards=[
            WildcardEntry(id="w1", name="color", entries=[{"text": "red"}, {"text": "blue"}])
        ],
        context_items=[ContextItemEntry(id="c1", title="House style", content="tight")],
        image_prompts=[ImagePromptEntry(id="ip1", name="moody", prompt="cinematic")],
        chain_sequences=[
            ChainSequenceEntry(
                id="s1",
                name="story-then-voice",
                steps=[{"id": "a", "name": "Draft", "type": "llm", "prompt": "x"}],
            )
        ],
        asset_manifest=[ProfileAsset(filename=asset_filename, kind="voice_wav")],
    )


def test_replace_mode_wipes_existing_and_applies_profile(isolated_config, tmp_path):
    # Seed existing config that should be GONE after replace.
    voice_presets_mod.save_preset("Stale", "old", b"OLDWAV")
    wildcards_mod.create_wildcard("stale_wc", [{"text": "x"}])
    context_library.create_item("stale ctx", [], "", "x")
    image_prompts_mod.create_prompt("stale prompt", "x")
    sequences.save_sequence("stale_seq", [{"id": "z", "name": "Z", "type": "llm"}])
    comfyui_cfg.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    (comfyui_cfg.WORKFLOWS_DIR / "stale.json").write_text("{}", encoding="utf-8")

    # Asset bundle on disk.
    asset_dir = tmp_path / "bundle"
    asset_dir.mkdir()
    (asset_dir / "vp1.wav").write_bytes(b"NEWWAV")

    profile = _profile_with_payload()
    report = apply_master_profile(profile, mode="replace", asset_source=asset_dir)

    # Per-domain counts.
    assert report.domains == {
        "llm_config": 1,
        "omnivoice": 1,
        "comfyui": 1,
        "comfyui_workflows": 1,
        "voice_presets": 1,
        "wildcards": 1,
        "context_items": 1,
        "image_prompts": 1,
        "chain_sequences": 1,
    }
    assert report.assets_copied == 1
    assert report.asset_warnings == []

    # llm_config replaced.
    llm_doc = json.loads(importer.LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    assert [p["id"] for p in llm_doc["presets"]] == ["llm-1"]
    assert llm_doc["default_preset_id"] == "llm-1"

    # omnivoice replaced.
    omnivoice_cfg._config = None
    assert omnivoice_cfg.get_config().speed == 1.3

    # comfyui replaced and stale workflow removed.
    comfyui_cfg._config = None
    assert comfyui_cfg.get_config().default_workflow == "flux-dev.json"
    workflow_files = sorted(p.name for p in comfyui_cfg.WORKFLOWS_DIR.glob("*.json"))
    assert workflow_files == ["flux-dev.json"]

    # Indexed domains replaced (no stale entries).
    assert [w["id"] for w in json.loads(wildcards_mod._INDEX_PATH.read_text())] == ["w1"]
    assert [c["id"] for c in json.loads(context_library.INDEX_PATH.read_text())] == ["c1"]
    assert [p["id"] for p in json.loads(image_prompts_mod.INDEX_PATH.read_text())] == ["ip1"]
    assert [s["id"] for s in json.loads(sequences.INDEX_PATH.read_text())] == ["s1"]

    vp_index = json.loads(voice_presets_mod.INDEX_PATH.read_text())
    assert [p["id"] for p in vp_index] == ["vp1"]
    # Asset copied to voice_presets dir.
    assert (voice_presets_mod.PRESETS_DIR / "vp1.wav").read_bytes() == b"NEWWAV"


def test_merge_mode_upserts_by_id_and_preserves_others(isolated_config, tmp_path):
    # Seed an existing entry per domain — should survive a merge that doesn't touch its id.
    wildcards_mod.create_wildcard("keepme_wc", [{"text": "k"}])
    keep_wc_id = json.loads(wildcards_mod._INDEX_PATH.read_text())[0]["id"]
    context_library.create_item("keepme ctx", [], "", "k")
    keep_ctx_id = json.loads(context_library.INDEX_PATH.read_text())[0]["id"]
    image_prompts_mod.create_prompt("keepme prompt", "k")
    keep_ip_id = json.loads(image_prompts_mod.INDEX_PATH.read_text())[0]["id"]
    sequences.save_sequence("keepme_seq", [{"id": "q", "name": "Q", "type": "llm"}])
    keep_seq_id = json.loads(sequences.INDEX_PATH.read_text())[0]["id"]

    # Asset for the voice preset upsert.
    asset_dir = tmp_path / "bundle"
    asset_dir.mkdir()
    (asset_dir / "vp1.wav").write_bytes(b"NEWWAV")

    profile = _profile_with_payload()
    report = apply_master_profile(profile, mode="merge", asset_source=asset_dir)

    # Merge sums: 1 existing + 1 new for each indexed domain.
    assert report.domains["wildcards"] == 2
    assert report.domains["context_items"] == 2
    assert report.domains["image_prompts"] == 2
    assert report.domains["chain_sequences"] == 2
    assert report.domains["voice_presets"] == 1  # no prior voice preset
    assert report.assets_copied == 1

    # Existing items still present alongside the new ones.
    wc_ids = {w["id"] for w in json.loads(wildcards_mod._INDEX_PATH.read_text())}
    assert wc_ids == {keep_wc_id, "w1"}
    ctx_ids = {c["id"] for c in json.loads(context_library.INDEX_PATH.read_text())}
    assert ctx_ids == {keep_ctx_id, "c1"}
    ip_ids = {p["id"] for p in json.loads(image_prompts_mod.INDEX_PATH.read_text())}
    assert ip_ids == {keep_ip_id, "ip1"}
    seq_ids = {s["id"] for s in json.loads(sequences.INDEX_PATH.read_text())}
    assert seq_ids == {keep_seq_id, "s1"}


def test_merge_upserts_by_overwriting_same_id(isolated_config, tmp_path):
    asset_dir = tmp_path / "bundle"
    asset_dir.mkdir()
    (asset_dir / "vp1.wav").write_bytes(b"NEWWAV")

    # First apply, then mutate the profile and re-apply in merge mode.
    apply_master_profile(_profile_with_payload(), mode="replace", asset_source=asset_dir)

    mutated = _profile_with_payload()
    mutated.wildcards[0].entries = [{"text": "green"}]  # same id, different content
    apply_master_profile(mutated, mode="merge", asset_source=asset_dir)

    wc = json.loads(wildcards_mod._INDEX_PATH.read_text())
    assert len(wc) == 1
    assert wc[0]["id"] == "w1"
    assert wc[0]["entries"] == [{"text": "green"}]


def test_missing_asset_records_warning_and_does_not_abort(isolated_config, tmp_path):
    # asset_source provided but the referenced file is missing.
    asset_dir = tmp_path / "empty_bundle"
    asset_dir.mkdir()

    profile = _profile_with_payload(asset_filename="missing.wav")
    report = apply_master_profile(profile, mode="replace", asset_source=asset_dir)

    assert report.assets_copied == 0
    assert len(report.asset_warnings) == 1
    assert "missing.wav" in report.asset_warnings[0]
    # Domains still applied normally despite the asset warning.
    assert report.domains["voice_presets"] == 1


def test_missing_asset_source_records_warning(isolated_config):
    profile = _profile_with_payload()
    report = apply_master_profile(profile, mode="replace", asset_source=None)
    assert report.assets_copied == 0
    assert any("no asset_source" in w for w in report.asset_warnings)


def test_unknown_mode_raises(isolated_config):
    with pytest.raises(ValueError):
        apply_master_profile(_profile_with_payload(), mode="overwrite")  # type: ignore[arg-type]
