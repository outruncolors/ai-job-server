"""MasterProfile schema bundling every domain of declarative server config.

A MasterProfile is the single JSON document that captures every per-domain
setting that determines server behavior. Exporting collapses live config into
one of these; importing applies one back over live config; bundling pairs the
JSON with the binary assets it references so a profile is portable across
hosts.

Domains covered (register new domains here when extending the schema):

    llm_config         app/llm_config.py             → LLMConfigDoc
    omnivoice          app/omnivoice/config.py       → OmniVoiceConfig
    comfyui            app/comfyui/config.py         → ComfyUIConfig
    comfyui_workflows  config/comfyui-workflows/*    → dict[name, workflow JSON]
    voice_presets      app/voice_presets.py          → list[VoicePresetEntry]
    wildcards          app/wildcards.py              → list[WildcardEntry]
    context_items      app/chain/context_library.py  → list[ContextItemEntry]
    image_prompts      app/image_prompts.py          → list[ImagePromptEntry]
    chain_sequences    app/chain/sequences.py        → list[ChainSequenceEntry]

Binary assets that cannot be inlined (currently only voice-cloning WAVs) are
referenced by filename on their preset entry and listed once in
`asset_manifest`. Packaging the asset bytes alongside the profile JSON is the
job of the bundle layer; this module only records the references.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..comfyui.config import ComfyUIConfig
from ..llm_config import LLMConfigDoc
from ..omnivoice.config import OmniVoiceConfig

SCHEMA_VERSION = "1"


class VoicePresetEntry(BaseModel):
    id: str
    name: str
    caption: str = ""
    wav_filename: str
    created_at: Optional[str] = None


class WildcardEntry(BaseModel):
    id: str
    name: str
    description: str = ""
    entries: list[dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ContextItemEntry(BaseModel):
    id: str
    title: str
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    content: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ImagePromptEntry(BaseModel):
    id: str
    name: str
    prompt: str
    workflow: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ChainSequenceEntry(BaseModel):
    id: str
    name: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProfileAsset(BaseModel):
    filename: str
    kind: Literal["voice_wav"] = "voice_wav"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MasterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    name: str
    description: str = ""
    created_at: str = Field(default_factory=_now_iso)

    llm_config: LLMConfigDoc = Field(default_factory=LLMConfigDoc)
    omnivoice: OmniVoiceConfig = Field(default_factory=OmniVoiceConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    comfyui_workflows: dict[str, dict[str, Any]] = Field(default_factory=dict)

    voice_presets: list[VoicePresetEntry] = Field(default_factory=list)
    wildcards: list[WildcardEntry] = Field(default_factory=list)
    context_items: list[ContextItemEntry] = Field(default_factory=list)
    image_prompts: list[ImagePromptEntry] = Field(default_factory=list)
    chain_sequences: list[ChainSequenceEntry] = Field(default_factory=list)

    asset_manifest: list[ProfileAsset] = Field(default_factory=list)
