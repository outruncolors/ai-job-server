"""Snapshot live ai-job-server config into a MasterProfile.

`build_master_profile` reads every domain's on-disk state and assembles a
single `MasterProfile`. `list_required_assets` returns the absolute paths of
binary files the profile depends on (currently only voice-cloning WAVs) so the
bundle layer knows what to ship alongside the profile JSON.

When a new domain is added to `MasterProfile`, register it here too.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import image_prompts, voice_presets, wildcards
from ..chain import context_library, sequences
from ..comfyui import config as comfyui_config
from ..llm_config import CONFIG_PATH as LLM_CONFIG_PATH, LLMConfigDoc
from ..omnivoice import config as omnivoice_config
from .models import MasterProfile, ProfileAsset, VoicePresetEntry


def _load_llm_config() -> LLMConfigDoc:
    if not LLM_CONFIG_PATH.exists():
        return LLMConfigDoc()
    return LLMConfigDoc.model_validate(
        json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    )


def _load_comfyui_workflows() -> list[str]:
    """Return just the filenames present in the workflows directory.

    Workflow file contents are managed by ComfyUI and not duplicated into the
    profile — the profile only records which names existed at snapshot time.
    """
    workflows_dir = comfyui_config.WORKFLOWS_DIR
    if not workflows_dir.exists():
        return []
    return sorted(p.name for p in workflows_dir.glob("*.json"))


def build_master_profile(name: str, description: str = "") -> MasterProfile:
    """Read every domain's current on-disk state into a fresh MasterProfile."""
    presets = [VoicePresetEntry.model_validate(e) for e in voice_presets.list_presets()]
    return MasterProfile(
        name=name,
        description=description,
        llm_config=_load_llm_config(),
        omnivoice=omnivoice_config.load_config(),
        comfyui=comfyui_config.load_config(),
        comfyui_workflows=_load_comfyui_workflows(),
        voice_presets=presets,
        # Stores already return unified Cruddable envelopes; pass them through.
        wildcards=wildcards.list_wildcards(),
        context_items=context_library.list_items(),
        image_prompts=image_prompts.list_prompts(),
        chain_sequences=sequences.list_sequences(),
        asset_manifest=[
            ProfileAsset(filename=p.wav_filename, kind="voice_wav") for p in presets
        ],
    )


def list_required_assets(profile: MasterProfile) -> list[Path]:
    """Absolute paths of binary files the profile references."""
    out: list[Path] = []
    for asset in profile.asset_manifest:
        if asset.kind == "voice_wav":
            out.append(voice_presets.PRESETS_DIR / asset.filename)
    return out
