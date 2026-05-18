from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH: Path = Path(
    os.environ.get(
        "LLAMACPP_CONFIG_PATH",
        str(PROJECT_ROOT / "config" / "llamacpp.json"),
    )
)

_config: Optional["LlamaCppConfig"] = None


class LlamaCppConfig(BaseModel):
    binary_path: str = "/opt/ai-stack/llama.cpp/build/bin/llama-server"
    port: int = 8080
    default_preset: Optional[str] = None
    models_dir: str = "/opt/ai-stack/models"


def load_config() -> LlamaCppConfig:
    global _config
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _config = LlamaCppConfig(**data)
            return _config
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    _config = LlamaCppConfig()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_config.model_dump_json(indent=2), encoding="utf-8")
    return _config


def save_config(config: LlamaCppConfig) -> None:
    global _config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    _config = config


def get_config() -> LlamaCppConfig:
    global _config
    if _config is None:
        return load_config()
    return _config
