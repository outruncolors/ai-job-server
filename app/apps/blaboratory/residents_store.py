"""File-per-document store for Blaboratory residents.

Each resident is its own JSON file at `config/blaboratory/residents/<id>.json`;
listing globs the directory. `id` / `schema_version` / `created_at` /
`updated_at` are assigned here (never by callers or the LLM). Follows the
existing JSON-store conventions (`app/image_prompts.py`, `app/tickets/store.py`):
a module-level `RESIDENTS_DIR` constant (monkeypatchable in tests) and atomic
writes (temp file + `os.replace`).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Resident

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESIDENTS_DIR: Path = PROJECT_ROOT / "config" / "blaboratory" / "residents"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_for(resident_id: str) -> Path:
    return RESIDENTS_DIR / f"{resident_id}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_residents() -> list[dict]:
    """All persisted residents (unordered)."""
    if not RESIDENTS_DIR.exists():
        return []
    out: list[dict] = []
    for p in RESIDENTS_DIR.glob("*.json"):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def get_resident(resident_id: str) -> Optional[dict]:
    p = _path_for(resident_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def create_resident(fields: dict) -> dict:
    """Build a new resident from character `fields`, assigning the
    server-controlled fields (`id`, `schema_version=1`, timestamps), validating
    the full document against `Resident`, and persisting it.
    """
    now = _now_iso()
    doc = dict(fields)
    doc["id"] = str(uuid.uuid4())
    doc["schema_version"] = 1
    doc["created_at"] = now
    doc["updated_at"] = now
    resident = Resident(**doc)
    data = resident.model_dump()
    _atomic_write(_path_for(resident.id), data)
    return data


def save_resident(resident: dict) -> dict:
    """Persist an existing resident document, bumping `updated_at`. Validates
    against `Resident`; requires an `id`.
    """
    if not resident.get("id"):
        raise ValueError("resident must have an id to save")
    doc = dict(resident)
    doc["updated_at"] = _now_iso()
    validated = Resident(**doc)
    data = validated.model_dump()
    _atomic_write(_path_for(validated.id), data)
    return data


def delete_resident(resident_id: str) -> bool:
    p = _path_for(resident_id)
    if not p.exists():
        return False
    p.unlink()
    return True
