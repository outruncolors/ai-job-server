from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH: Path = Path(
    os.environ.get(
        "COMFYUI_CONFIG_PATH",
        str(PROJECT_ROOT / "config" / "comfyui.json"),
    )
)

WORKFLOWS_DIR: Path = PROJECT_ROOT / "config" / "comfyui-workflows"

_config: Optional[ComfyUIConfig] = None


class ComfyUIConfig(BaseModel):
    # Process location
    comfyui_root: str = "/opt/ai-stack/runtimes/ComfyUI"
    venv_python: str = "/opt/ai-stack/runtimes/comfyui-venv/bin/python"
    # Network
    host: str = "127.0.0.1"
    port: int = 8188
    autostart: bool = True
    # Launch optimizations
    use_sage_attention: bool = True
    vram_mode: str = "highvram"  # highvram | normalvram | lowvram | novram
    reserve_vram_gb: float = 1.0
    preview_method: str = "none"  # none | auto | latent2rgb | taesd
    extra_args: List[str] = Field(default_factory=list)
    # Paths
    models_root: str = "/opt/ai-stack/models"
    output_dir: str = "/var/lib/comfy/output"
    input_dir: str = "/var/lib/comfy/input"
    extra_model_paths_yaml: str = "/opt/ai-stack/models/extra_model_paths.yaml"
    # Workflow defaults
    default_workflow: Optional[str] = None


def load_config() -> ComfyUIConfig:
    global _config
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _config = ComfyUIConfig(**data)
            return _config
    except Exception:
        pass
    _config = ComfyUIConfig()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_config.model_dump_json(indent=2), encoding="utf-8")
    return _config


def save_config(config: ComfyUIConfig) -> None:
    global _config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    _config = config


def get_config() -> ComfyUIConfig:
    global _config
    if _config is None:
        return load_config()
    return _config
