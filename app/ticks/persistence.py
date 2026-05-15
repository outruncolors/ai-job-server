from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TICKS_DIR: Path = PROJECT_ROOT / "config" / "ticks"
INDEX_PATH: Path = TICKS_DIR / "index.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    TICKS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def list_ticks() -> list[dict]:
    return _read_index()


def get_tick(tick_id: str) -> Optional[dict]:
    return next((t for t in _read_index() if t["id"] == tick_id), None)


def save_tick(tick_dict: dict) -> dict:
    entries = _read_index()
    now = _now_iso()
    existing = next((e for e in entries if e["id"] == tick_dict.get("id")), None)
    if existing:
        existing.update(tick_dict)
        existing["updated_at"] = now
        _write_index(entries)
        return existing
    tick_dict.setdefault("id", str(uuid.uuid4()))
    tick_dict.setdefault("created_at", now)
    tick_dict["updated_at"] = now
    entries.append(tick_dict)
    _write_index(entries)
    return tick_dict


def delete_tick(tick_id: str) -> bool:
    entries = _read_index()
    new_entries = [e for e in entries if e["id"] != tick_id]
    if len(new_entries) == len(entries):
        return False
    _write_index(new_entries)
    return True


def update_tick_fields(tick_id: str, **fields) -> Optional[dict]:
    entries = _read_index()
    entry = next((e for e in entries if e["id"] == tick_id), None)
    if entry is None:
        return None
    entry.update(fields)
    entry["updated_at"] = _now_iso()
    _write_index(entries)
    return entry
