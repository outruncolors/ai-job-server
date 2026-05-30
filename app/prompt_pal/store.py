"""File-per-document store for Prompt Pal entries.

Each entry is its own JSON file at ``config/prompt_pal/<id>.json``; listing globs
the directory. ``id`` / ``schema_version`` / ``created_at`` / ``updated_at`` are
assigned here. Follows the existing store conventions
(``app/apps/blaboratory/residents_store.py``): a module-level ``PROMPT_PAL_DIR``
constant (monkeypatchable in tests) and atomic writes (temp file + ``os.replace``).

File-per-doc (not a single JSON index) because prompt bodies are large multi-line
text that diff/churn badly in one growing file, and because ``app/profiles/``
bundles config sub-dirs cleanly per-doc.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .compose import PromptNode
from .models import PromptEntry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PAL_DIR: Path = PROJECT_ROOT / "config" / "prompt_pal"

# Fields a PUT may change. `app`/`key` are immutable code contracts.
_PATCHABLE = {"title", "description", "tags", "prompt", "variables", "guard"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_for(entry_id: str) -> Path:
    return PROMPT_PAL_DIR / f"{entry_id}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_entries() -> list[dict]:
    """All persisted prompt entries (unordered)."""
    if not PROMPT_PAL_DIR.exists():
        return []
    out: list[dict] = []
    for p in PROMPT_PAL_DIR.glob("*.json"):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def get_entry(entry_id: str) -> Optional[dict]:
    p = _path_for(entry_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def get_by_app_key(app: str, key: str) -> Optional[dict]:
    """First entry matching ``(app, key)``, or None. Scans the directory."""
    for entry in list_entries():
        if entry.get("app") == app and entry.get("key") == key:
            return entry
    return None


def create_entry(fields: dict) -> dict:
    """Create a new entry from ``fields``, assigning ``id`` / ``schema_version`` /
    timestamps, validating against ``PromptEntry``, and persisting it.
    """
    now = _now_iso()
    doc = dict(fields)
    doc["id"] = str(uuid.uuid4())
    doc["schema_version"] = 1
    doc["created_at"] = now
    doc["updated_at"] = now
    entry = PromptEntry(**doc)
    data = entry.model_dump()
    _atomic_write(_path_for(entry.id), data)
    return data


def save_entry(entry: dict) -> dict:
    """Persist an existing entry document, bumping ``updated_at``. Requires an
    ``id``; validates against ``PromptEntry``.
    """
    if not entry.get("id"):
        raise ValueError("entry must have an id to save")
    doc = dict(entry)
    doc["updated_at"] = _now_iso()
    validated = PromptEntry(**doc)
    data = validated.model_dump()
    _atomic_write(_path_for(validated.id), data)
    return data


def update_entry(entry_id: str, **patch) -> Optional[dict]:
    """Apply a patch (only ``_PATCHABLE`` keys) and persist. None if missing."""
    current = get_entry(entry_id)
    if current is None:
        return None
    for k, v in patch.items():
        if k in _PATCHABLE and v is not None:
            current[k] = v
    return save_entry(current)


def delete_entry(entry_id: str) -> bool:
    p = _path_for(entry_id)
    if not p.exists():
        return False
    p.unlink()
    return True


def node_for_id(entry_id: str) -> Optional[PromptNode]:
    """Return the stored entry as a compose ``PromptNode`` (``{prompt, variables}``),
    or None. This is the ``store=`` callable for resolving ``{"prompt_id": id}``
    references inside other prompts.
    """
    entry = get_entry(entry_id)
    if entry is None:
        return None
    return {"prompt": entry.get("prompt", ""), "variables": entry.get("variables") or {}}
