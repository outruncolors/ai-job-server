"""File-per-document store for composable prompt assets.

Each asset is a prompt node (``{"prompt": ..., "variables": {...}}`` or a plain
string) stored at ``config/blaboratory/prompts/<id>.json``. These back the
``{"prompt_id": "<id>"}`` references resolved by ``prompt_compose.compose``;
pass ``get_prompt_asset`` as the ``store`` callable.

Same conventions as the other Blaboratory stores: module-level ``PROMPTS_DIR``
(monkeypatchable), atomic writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .prompt_compose import PromptNode

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR: Path = PROJECT_ROOT / "config" / "blaboratory" / "prompts"


def _path_for(prompt_id: str) -> Path:
    return PROMPTS_DIR / f"{prompt_id}.json"


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def get_prompt_asset(prompt_id: str) -> Optional[PromptNode]:
    """The stored prompt node for ``prompt_id``, or None if absent."""
    p = _path_for(prompt_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_prompt_assets() -> dict[str, PromptNode]:
    """All stored prompt nodes keyed by id."""
    if not PROMPTS_DIR.exists():
        return {}
    out: dict[str, PromptNode] = {}
    for path in PROMPTS_DIR.glob("*.json"):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def save_prompt_asset(prompt_id: str, node: PromptNode) -> PromptNode:
    """Persist a prompt node under ``prompt_id``; returns the node."""
    _atomic_write(_path_for(prompt_id), node)
    return node
