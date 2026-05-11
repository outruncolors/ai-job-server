from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ITEMS_DIR: Path = PROJECT_ROOT / "config" / "context_items"
INDEX_PATH: Path = ITEMS_DIR / "index.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def list_items() -> list[dict]:
    return _read_index()


def create_item(title: str, tags: list[str], description: str, content: str) -> dict:
    entries = _read_index()
    now = _now_iso()
    entry = {
        "id": str(uuid.uuid4()),
        "title": title,
        "tags": tags,
        "description": description,
        "content": content,
        "created_at": now,
        "updated_at": now,
    }
    entries.append(entry)
    _write_index(entries)
    return entry


def get_item(item_id: str) -> Optional[dict]:
    entries = _read_index()
    return next((e for e in entries if e["id"] == item_id), None)


def update_item(item_id: str, **fields) -> Optional[dict]:
    entries = _read_index()
    entry = next((e for e in entries if e["id"] == item_id), None)
    if entry is None:
        return None
    allowed = {"title", "tags", "description", "content"}
    for k, v in fields.items():
        if k in allowed:
            entry[k] = v
    entry["updated_at"] = _now_iso()
    _write_index(entries)
    return entry


def delete_item(item_id: str) -> bool:
    entries = _read_index()
    new_entries = [e for e in entries if e["id"] != item_id]
    if len(new_entries) == len(entries):
        return False
    _write_index(new_entries)
    return True
