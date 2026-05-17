from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.profiles.models import (
    SCHEMA_VERSION,
    ChainSequenceEntry,
    ContextItemEntry,
    ImagePromptEntry,
    MasterProfile,
    ProfileAsset,
    VoicePresetEntry,
    WildcardEntry,
)


def _fully_populated() -> MasterProfile:
    return MasterProfile(
        name="house-style",
        description="Snapshot of the live config on 2026-05-16",
        created_at="2026-05-16T12:00:00+00:00",
        llm_config={
            "presets": [
                {
                    "id": "p1",
                    "name": "local-gemma",
                    "api_base": "http://127.0.0.1:8080/v1",
                    "model": "gemma-3-27b",
                    "temperature": 0.4,
                    "max_tokens": 4096,
                    "timeout_seconds": 60,
                }
            ],
            "default_preset_id": "p1",
        },
        omnivoice={
            "model": "k2-fsa/OmniVoice",
            "response_format": "wav",
            "voice": "default",
            "speed": 1.1,
            "ref_audio_filename": "narrator.wav",
            "ref_text": "Once upon a time",
        },
        comfyui={
            "comfyui_root": "/opt/ai-stack/runtimes/ComfyUI",
            "venv_python": "/opt/ai-stack/runtimes/comfyui-venv/bin/python",
            "host": "127.0.0.1",
            "port": 8188,
            "default_workflow": "flux-dev.json",
        },
        comfyui_workflows=["flux-dev.json", "flux-schnell.json"],
        voice_presets=[
            VoicePresetEntry(
                id="vp1",
                name="Narrator",
                caption="warm, mid-range",
                wav_filename="vp1.wav",
                created_at="2026-05-16T10:00:00+00:00",
            )
        ],
        wildcards=[
            WildcardEntry(
                id="w1",
                name="color",
                description="basic palette",
                entries=[{"text": "red"}, {"text": "blue"}],
                created_at="2026-05-16T10:00:00+00:00",
                updated_at="2026-05-16T10:00:00+00:00",
            )
        ],
        context_items=[
            ContextItemEntry(
                id="c1",
                title="House style",
                tags=["style", "voice"],
                description="Tone guide",
                content="Write in short, direct sentences.",
                created_at="2026-05-16T10:00:00+00:00",
                updated_at="2026-05-16T10:00:00+00:00",
            )
        ],
        image_prompts=[
            ImagePromptEntry(
                id="ip1",
                name="moody portrait",
                prompt="cinematic portrait, %%color%% lighting",
                workflow="flux-dev.json",
                created_at="2026-05-16T10:00:00+00:00",
                updated_at="2026-05-16T10:00:00+00:00",
            )
        ],
        chain_sequences=[
            ChainSequenceEntry(
                id="s1",
                name="story-then-voice",
                steps=[
                    {"id": "a", "name": "Draft", "type": "llm", "prompt": "Write a scene"},
                    {"id": "b", "name": "Read", "type": "voice", "voice_preset_id": "vp1"},
                ],
                created_at="2026-05-16T10:00:00+00:00",
                updated_at="2026-05-16T10:00:00+00:00",
            )
        ],
        asset_manifest=[ProfileAsset(filename="vp1.wav", kind="voice_wav")],
    )


def test_defaults_populate_empty_collections():
    p = MasterProfile(name="empty")
    assert p.schema_version == SCHEMA_VERSION
    assert p.description == ""
    assert p.created_at  # default factory ran
    assert p.llm_config.presets == []
    assert p.llm_config.default_preset_id is None
    assert p.comfyui_workflows == []
    assert p.voice_presets == []
    assert p.wildcards == []
    assert p.context_items == []
    assert p.image_prompts == []
    assert p.chain_sequences == []
    assert p.asset_manifest == []


def test_round_trip_via_dict():
    original = _fully_populated()
    dumped = original.model_dump()
    restored = MasterProfile.model_validate(dumped)
    assert restored.model_dump() == dumped


def test_round_trip_via_json():
    original = _fully_populated()
    payload = original.model_dump_json()
    restored = MasterProfile.model_validate_json(payload)
    assert restored.model_dump_json() == payload
    # The JSON itself should be parseable plain JSON.
    parsed = json.loads(payload)
    assert parsed["name"] == "house-style"
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["voice_presets"][0]["wav_filename"] == "vp1.wav"
    assert parsed["asset_manifest"][0]["kind"] == "voice_wav"


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        MasterProfile.model_validate(
            {"name": "x", "future_field": "boom"}
        )


def test_name_is_required():
    with pytest.raises(ValidationError):
        MasterProfile.model_validate({})


def test_voice_preset_requires_wav_filename():
    with pytest.raises(ValidationError):
        VoicePresetEntry.model_validate({"id": "x", "name": "y"})


def test_asset_kind_constrained_to_known_values():
    with pytest.raises(ValidationError):
        ProfileAsset.model_validate({"filename": "x", "kind": "lora"})
