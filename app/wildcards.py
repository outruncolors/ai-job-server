from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DIR: Path = PROJECT_ROOT / "config" / "wildcards"
_INDEX_PATH: Path = _DIR / "index.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not _INDEX_PATH.exists():
        return []
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def list_wildcards() -> list[dict]:
    return _read_index()


def create_wildcard(name: str, entries: list[dict]) -> dict:
    items = _read_index()
    now = _now_iso()
    item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "entries": entries,
        "created_at": now,
        "updated_at": now,
    }
    items.append(item)
    _write_index(items)
    return item


def update_wildcard(wid: str, name: str, entries: list[dict]) -> Optional[dict]:
    items = _read_index()
    item = next((e for e in items if e["id"] == wid), None)
    if item is None:
        return None
    item["name"] = name
    item["entries"] = entries
    item["updated_at"] = _now_iso()
    _write_index(items)
    return item


def delete_wildcard(wid: str) -> bool:
    items = _read_index()
    new_items = [e for e in items if e["id"] != wid]
    if len(new_items) == len(items):
        return False
    _write_index(new_items)
    return True
