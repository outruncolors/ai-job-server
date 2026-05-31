"""Context-item store — persists the unified Cruddable envelope.

On disk (``config/context_items/index.json``) each item is an envelope:
``{schema_version,type:"context_item",id,name,description,tags,created_at,updated_at,
data:{content}}``. The legacy field ``title`` maps to the envelope meta ``name``; ``content``
moves under ``data``; ``tags``/``description`` are envelope meta. IDs are human-readable slugs.

Context items are referenced by **id** from chain alternatives' ``context_ids`` — the
one-time migration in ``app.cruddables.migrate`` rewrites those references when re-slugging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.cruddables.envelope import now_iso, slugify, unique_id

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ITEMS_DIR: Path = PROJECT_ROOT / "config" / "context_items"
INDEX_PATH: Path = ITEMS_DIR / "index.json"

TYPE_NAME = "context_item"


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _normalize(doc: dict) -> dict:
    """Return ``doc`` as an envelope, reshaping a legacy flat context item if needed."""
    if doc.get("type") == TYPE_NAME and isinstance(doc.get("data"), dict):
        doc.setdefault("tags", [])
        doc.setdefault("description", "")
        return doc
    now = now_iso()
    return {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": doc.get("id") or slugify(doc.get("title") or doc.get("name") or "context"),
        "name": doc.get("name") or doc.get("title") or "",
        "description": doc.get("description") or "",
        "tags": doc.get("tags") or [],
        "created_at": doc.get("created_at") or now,
        "updated_at": doc.get("updated_at") or now,
        "data": {"content": doc.get("content") or ""},
    }


def _taken_ids(items: list[dict]) -> set[str]:
    return {it["id"] for it in items if it.get("id")}


def list_items() -> list[dict]:
    return [_normalize(dict(it)) for it in _read_index()]


def get_item(item_id: str) -> Optional[dict]:
    return next((e for e in list_items() if e["id"] == item_id), None)


def create_item(title: str, tags: list[str], description: str, content: str) -> dict:
    items = list_items()
    now = now_iso()
    new_id = unique_id(slugify(title or "context"), _taken_ids(items))
    entry = {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": new_id,
        "name": title,
        "description": description,
        "tags": tags,
        "created_at": now,
        "updated_at": now,
        "data": {"content": content},
    }
    items.append(entry)
    _write_index(items)
    return entry


# Map the legacy update kwargs onto envelope fields.
def update_item(item_id: str, **fields) -> Optional[dict]:
    items = list_items()
    entry = next((e for e in items if e["id"] == item_id), None)
    if entry is None:
        return None
    if "title" in fields:
        entry["name"] = fields["title"]
    if "name" in fields:
        entry["name"] = fields["name"]
    if "tags" in fields:
        entry["tags"] = fields["tags"]
    if "description" in fields:
        entry["description"] = fields["description"]
    if "content" in fields:
        entry["data"] = {**(entry.get("data") or {}), "content": fields["content"]}
    entry["updated_at"] = now_iso()
    _write_index(items)
    return entry


def delete_item(item_id: str) -> bool:
    items = list_items()
    new_items = [e for e in items if e["id"] != item_id]
    if len(new_items) == len(items):
        return False
    _write_index(new_items)
    return True


def upsert_envelope(env: dict) -> tuple[str, str]:
    items = list_items()
    idx = next((i for i, e in enumerate(items) if e["id"] == env["id"]), None)
    now = now_iso()
    doc = _normalize(dict(env))
    if idx is None:
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        items.append(doc)
        action = "created"
    else:
        doc["created_at"] = items[idx].get("created_at") or now
        doc["updated_at"] = now
        items[idx] = doc
        action = "updated"
    _write_index(items)
    return action, doc["id"]
