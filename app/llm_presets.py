from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from .llm.models import LLMPreset
from .omnivoice.config import PROJECT_ROOT

PRESETS_DIR: Path = PROJECT_ROOT / "config" / "llm_presets"

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _path_for(name: str) -> Path:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid preset name: {name!r}")
    return PRESETS_DIR / f"{name}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_presets() -> list[dict]:
    if not PRESETS_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(LLMPreset(**data).model_dump())
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return out


def get_preset(name: str) -> Optional[dict]:
    try:
        path = _path_for(name)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMPreset(**data).model_dump()
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_preset(preset: LLMPreset) -> dict:
    path = _path_for(preset.name)
    _atomic_write(path, preset.model_dump())
    return preset.model_dump()


def delete_preset(name: str) -> bool:
    try:
        path = _path_for(name)
    except ValueError:
        return False
    if not path.exists():
        return False
    path.unlink()
    return True
