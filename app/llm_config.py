from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .chain.models import ChainLLMConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH: Path = PROJECT_ROOT / "config" / "llm_config.json"


class LLMPreset(BaseModel):
    id: str
    name: str
    api_base: str
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)


class LLMConfigDoc(BaseModel):
    presets: list[LLMPreset] = []
    default_preset_id: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> LLMConfigDoc:
    if not CONFIG_PATH.exists():
        return LLMConfigDoc()
    return LLMConfigDoc.model_validate(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))


def _write(doc: LLMConfigDoc) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(doc.model_dump_json(indent=2), encoding="utf-8")


def list_presets() -> dict:
    doc = _read()
    return {"presets": [p.model_dump() for p in doc.presets], "default_preset_id": doc.default_preset_id}


def save_preset(data: dict) -> LLMPreset:
    doc = _read()
    incoming_id = data.get("id")
    existing = None
    if incoming_id:
        existing = next((p for p in doc.presets if p.id == incoming_id), None)
    if existing is None:
        existing = next((p for p in doc.presets if p.name == data["name"]), None)
    if existing:
        for k, v in data.items():
            if k != "id" and hasattr(existing, k):
                setattr(existing, k, v)
        _write(doc)
        return existing
    preset = LLMPreset(id=incoming_id or str(uuid.uuid4()),
                      **{k: v for k, v in data.items() if k != "id"})
    doc.presets.append(preset)
    _write(doc)
    return preset


def delete_preset(preset_id: str) -> bool:
    doc = _read()
    new_presets = [p for p in doc.presets if p.id != preset_id]
    if len(new_presets) == len(doc.presets):
        return False
    if doc.default_preset_id == preset_id:
        doc.default_preset_id = None
    doc.presets = new_presets
    _write(doc)
    return True


def set_default(preset_id: Optional[str]) -> bool:
    doc = _read()
    if preset_id is not None and not any(p.id == preset_id for p in doc.presets):
        return False
    doc.default_preset_id = preset_id
    _write(doc)
    return True


def get_default() -> Optional[LLMPreset]:
    doc = _read()
    if not doc.default_preset_id:
        return None
    return next((p for p in doc.presets if p.id == doc.default_preset_id), None)


def get_default_as_chain_llm_config() -> ChainLLMConfig:
    preset = get_default()
    if preset is None:
        raise RuntimeError("No default LLM preset configured — set one on the Server page")
    return ChainLLMConfig(
        api_base=preset.api_base,
        model=preset.model,
        temperature=preset.temperature,
        max_tokens=preset.max_tokens,
        timeout_seconds=preset.timeout_seconds,
    )
