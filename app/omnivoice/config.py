from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH: Path = Path(
    os.environ.get(
        "OMNIVOICE_CONFIG_PATH",
        str(PROJECT_ROOT / "config" / "omnivoice.json"),
    )
)

_config: Optional[OmniVoiceConfig] = None


class OmniVoiceConfig(BaseModel):
    model: str = "k2-fsa/OmniVoice"
    response_format: str = "wav"
    voice: str = "default"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    language: Optional[str] = None
    instruct: Optional[str] = None
    ref_audio_filename: Optional[str] = None
    ref_text: Optional[str] = None
    infer_base_command: Optional[List[str]] = None


def load_config() -> OmniVoiceConfig:
    global _config
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _config = OmniVoiceConfig(**data)
            return _config
    except Exception:
        pass
    _config = OmniVoiceConfig()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_config.model_dump_json(indent=2), encoding="utf-8")
    return _config


def save_config(config: OmniVoiceConfig) -> None:
    global _config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    _config = config


def get_config() -> OmniVoiceConfig:
    global _config
    if _config is None:
        return load_config()
    return _config
