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
    host: str = "0.0.0.0"
    port: int = 8080
    default_preset: Optional[str] = None
    # Preset (in config/llm_presets/) holding the multimodal model + mmproj used
    # by the Vision and Speech-to-Text features. The same preset serves both, so
    # switching between them never reloads the model. None → those features 503.
    multimodal_preset: Optional[str] = "gemma-4-e4b-mm"
    # Floor for the multimodal preset's `ctx_size` at load time. Image embeddings
    # eat a big share of context, so a small preset ctx truncates long Vision
    # descriptions / STT transcripts (finish_reason=length). The swap raises the
    # preset's ctx_size to at least this (never lowers a larger value) and drops
    # any output cap. Lower it if the llm node is VRAM-constrained.
    multimodal_min_ctx: int = 8192
    models_dir: str = "/opt/ai-stack/models"
    # Embed server (D1): a second, always-on llama-server serving /v1/embeddings.
    # Managed by LlamaCppEmbedManager on llm-capable nodes (default bge-small,
    # 384-dim, CLS pooling). `embed_model_path` None → embed server stays down.
    embed_port: int = 8081
    embed_model_path: Optional[str] = None
    embed_pooling: str = "cls"


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
