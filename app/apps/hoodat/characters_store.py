"""File-per-document store for Hoodat characters.

Each character is its own JSON file at `config/hoodat/characters/<id>.json`;
listing globs the directory. `id` / `schema_version` / timestamps are assigned
here (never by callers or the LLM). Mirrors the Blaboratory residents store:
a module-level `CHARACTERS_DIR` constant (monkeypatchable) and atomic writes.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Character

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHARACTERS_DIR: Path = PROJECT_ROOT / "config" / "hoodat" / "characters"

# Sections that are nested blocks (vs `identity`, which is top-level fields).
_NESTED_SECTIONS = {"appearance", "personality", "background", "speaking_style"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_for(character_id: str) -> Path:
    return CHARACTERS_DIR / f"{character_id}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_characters() -> list[dict]:
    """All persisted characters (unordered)."""
    if not CHARACTERS_DIR.exists():
        return []
    out: list[dict] = []
    for p in CHARACTERS_DIR.glob("*.json"):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def get_character(character_id: str) -> Optional[dict]:
    p = _path_for(character_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def create_character(fields: dict) -> dict:
    """Build a new character from `fields`, assigning server-controlled fields
    (`id`, `schema_version=1`, timestamps), validating against `Character`, and
    persisting it.
    """
    now = _now_iso()
    doc = dict(fields)
    doc["id"] = str(uuid.uuid4())
    doc["schema_version"] = 1
    doc["created_at"] = now
    doc["updated_at"] = now
    character = Character(**doc)
    data = character.model_dump()
    _atomic_write(_path_for(character.id), data)
    return data


def save_character(character: dict) -> dict:
    """Persist an existing character document, bumping `updated_at`."""
    if not character.get("id"):
        raise ValueError("character must have an id to save")
    doc = dict(character)
    doc["updated_at"] = _now_iso()
    validated = Character(**doc)
    data = validated.model_dump()
    _atomic_write(_path_for(validated.id), data)
    return data


def update_character_fields(character_id: str, patch: dict) -> Optional[dict]:
    """Deep-merge a nested `patch` into the character and persist.

    `patch` may carry top-level identity fields and/or per-section sub-dicts
    (e.g. `{"name": "...", "appearance": {"primary_outfit": "..."}}`). None if
    the character is missing.
    """
    current = get_character(character_id)
    if current is None:
        return None
    for key, value in patch.items():
        if key in _NESTED_SECTIONS and isinstance(value, dict):
            block = dict(current.get(key) or {})
            block.update(value)
            current[key] = block
        else:
            current[key] = value
    return save_character(current)


def delete_character(character_id: str) -> bool:
    p = _path_for(character_id)
    if not p.exists():
        return False
    p.unlink()
    return True
