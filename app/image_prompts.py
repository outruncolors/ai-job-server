"""Image-prompt store — persists the unified Cruddable envelope.

On disk (``config/image_prompts/index.json``) each item is an envelope:
``{schema_version,type:"image_prompt",id,name,description,tags,created_at,updated_at,
data:{prompt,workflow}}``. IDs are human-readable slugs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.cruddables.envelope import now_iso, slugify, unique_id

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR: Path = PROJECT_ROOT / "config" / "image_prompts"
INDEX_PATH: Path = PROMPTS_DIR / "index.json"

TYPE_NAME = "image_prompt"
ALLOWED_UPDATE_FIELDS = {"name", "prompt", "workflow", "description"}


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _normalize(doc: dict) -> dict:
    if doc.get("type") == TYPE_NAME and isinstance(doc.get("data"), dict):
        doc.setdefault("tags", [])
        doc.setdefault("description", "")
        return doc
    now = now_iso()
    return {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": doc.get("id") or slugify(doc.get("name") or "image_prompt"),
        "name": doc.get("name") or "",
        "description": doc.get("description") or "",
        "tags": doc.get("tags") or [],
        "created_at": doc.get("created_at") or now,
        "updated_at": doc.get("updated_at") or now,
        "data": {"prompt": doc.get("prompt") or "", "workflow": doc.get("workflow")},
    }


def _taken_ids(items: list[dict]) -> set[str]:
    return {it["id"] for it in items if it.get("id")}


def _unique_name(base_name: str, existing_names: list[str]) -> str:
    """Image prompts keep display names unique (legacy UX): ``Dup`` → ``Dup (2)``."""
    if base_name not in existing_names:
        return base_name
    n = 2
    while f"{base_name} ({n})" in existing_names:
        n += 1
    return f"{base_name} ({n})"


def list_prompts() -> list[dict]:
    return [_normalize(dict(it)) for it in _read_index()]


def get_prompt(prompt_id: str) -> Optional[dict]:
    return next((e for e in list_prompts() if e["id"] == prompt_id), None)


def create_prompt(name: str, prompt: str, workflow: Optional[str] = None) -> dict:
    if not name or not name.strip():
        raise ValueError("name is required")
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")
    items = list_prompts()
    now = now_iso()
    final_name = _unique_name(name.strip(), [e["name"] for e in items])
    new_id = unique_id(slugify(final_name), _taken_ids(items))
    entry = {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": new_id,
        "name": final_name,
        "description": "",
        "tags": [],
        "created_at": now,
        "updated_at": now,
        "data": {"prompt": prompt, "workflow": workflow},
    }
    items.append(entry)
    _write_index(items)
    return entry


def update_prompt(prompt_id: str, **fields) -> Optional[dict]:
    items = list_prompts()
    entry = next((e for e in items if e["id"] == prompt_id), None)
    if entry is None:
        return None
    for k, v in fields.items():
        if k not in ALLOWED_UPDATE_FIELDS:
            continue
        if k == "name":
            if not v or not str(v).strip():
                raise ValueError("name is required")
            other_names = [e["name"] for e in items if e["id"] != prompt_id]
            entry["name"] = _unique_name(str(v).strip(), other_names)
        elif k == "description":
            entry["description"] = v
        else:  # prompt / workflow live under data
            entry["data"] = {**(entry.get("data") or {}), k: v}
    entry["updated_at"] = now_iso()
    _write_index(items)
    return entry


def delete_prompt(prompt_id: str) -> bool:
    items = list_prompts()
    new_items = [e for e in items if e["id"] != prompt_id]
    if len(new_items) == len(items):
        return False
    _write_index(new_items)
    return True


def upsert_envelope(env: dict) -> tuple[str, str]:
    items = list_prompts()
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
