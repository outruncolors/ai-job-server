"""File-per-document store for Prompt Pal entries — unified Cruddable envelope.

Each entry is its own JSON file at ``config/prompt_pal/<id>.json`` in the shared envelope
shape:
``{schema_version,type:"prompt_pal",id,name,description,tags,created_at,updated_at,
data:{app,key,prompt,variables,guard}}``.

The logical key code references is ``(data.app, data.key)`` (e.g.
``("hoodat","field.appearance.primary_outfit")``); ``id`` is a human-readable slug derived
from ``app_key`` and is the deep-link surrogate + filename. ``name`` is the display title.
When an entry is created without an ``app`` it defaults to ``"system"`` (user-authored
entries not owned by a specific app).

File-per-doc (not a single JSON index) because prompt bodies are large multi-line text.
Atomic writes (temp file + ``os.replace``); ``PROMPT_PAL_DIR`` is monkeypatchable in tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app.cruddables.envelope import now_iso, slugify, unique_id

from .compose import PromptNode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PAL_DIR: Path = PROJECT_ROOT / "config" / "prompt_pal"

TYPE_NAME = "prompt_pal"
DEFAULT_APP = "system"

# Flat input keys a create/patch may carry; mapped into the envelope.
_PATCHABLE = {"title", "description", "tags", "prompt", "variables", "guard"}


def _path_for(entry_id: str) -> Path:
    return PROMPT_PAL_DIR / f"{entry_id}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _normalize(doc: dict) -> dict:
    """Return ``doc`` as an envelope, reshaping a legacy flat PromptEntry if needed."""
    if doc.get("type") == TYPE_NAME and isinstance(doc.get("data"), dict):
        doc.setdefault("tags", [])
        doc.setdefault("description", "")
        return doc
    now = now_iso()
    app = doc.get("app") or DEFAULT_APP
    key = doc.get("key") or ""
    return {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": doc.get("id") or slugify(f"{app}_{key}"),
        "name": doc.get("title") or doc.get("name") or "",
        "description": doc.get("description") or "",
        "tags": doc.get("tags") or [],
        "created_at": doc.get("created_at") or now,
        "updated_at": doc.get("updated_at") or now,
        "data": {
            "app": app,
            "key": key,
            "prompt": doc.get("prompt") or "",
            "variables": doc.get("variables") or {},
            "guard": doc.get("guard"),
        },
    }


def _envelope_from_flat(fields: dict, *, taken_ids: set[str]) -> dict:
    """Build a fresh envelope from flat create-input fields."""
    app = fields.get("app") or DEFAULT_APP
    key = fields.get("key") or ""
    now = now_iso()
    new_id = unique_id(slugify(f"{app}_{key}"), taken_ids)
    return {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": new_id,
        "name": fields.get("title") or fields.get("name") or "",
        "description": fields.get("description") or "",
        "tags": list(fields.get("tags") or []),
        "created_at": now,
        "updated_at": now,
        "data": {
            "app": app,
            "key": key,
            "prompt": fields.get("prompt") or "",
            "variables": dict(fields.get("variables") or {}),
            "guard": fields.get("guard"),
        },
    }


def list_entries() -> list[dict]:
    """All persisted prompt entries (unordered)."""
    if not PROMPT_PAL_DIR.exists():
        return []
    out: list[dict] = []
    for p in PROMPT_PAL_DIR.glob("*.json"):
        out.append(_normalize(json.loads(p.read_text(encoding="utf-8"))))
    return out


def get_entry(entry_id: str) -> Optional[dict]:
    p = _path_for(entry_id)
    if not p.exists():
        return None
    return _normalize(json.loads(p.read_text(encoding="utf-8")))


def get_by_app_key(app: str, key: str) -> Optional[dict]:
    """First entry matching ``(app, key)`` on the envelope ``data``, or None."""
    for entry in list_entries():
        d = entry.get("data") or {}
        if d.get("app") == app and d.get("key") == key:
            return entry
    return None


def _taken_ids() -> set[str]:
    return {e["id"] for e in list_entries() if e.get("id")}


def create_entry(fields: dict) -> dict:
    """Create a new entry from flat ``fields`` ({app,key,title,prompt,variables,guard,
    description,tags}), assigning id/timestamps and persisting it as an envelope."""
    doc = _envelope_from_flat(fields, taken_ids=_taken_ids())
    _atomic_write(_path_for(doc["id"]), doc)
    return doc


def save_entry(entry: dict) -> dict:
    """Persist an existing envelope document, bumping ``updated_at``. Requires an ``id``."""
    if not entry.get("id"):
        raise ValueError("entry must have an id to save")
    doc = _normalize(dict(entry))
    doc["updated_at"] = now_iso()
    _atomic_write(_path_for(doc["id"]), doc)
    return doc


def update_entry(entry_id: str, **patch) -> Optional[dict]:
    """Apply a flat patch (only ``_PATCHABLE`` keys) and persist. None if missing."""
    current = get_entry(entry_id)
    if current is None:
        return None
    for k, v in patch.items():
        if k not in _PATCHABLE or v is None:
            continue
        if k == "title":
            current["name"] = v
        elif k in ("description", "tags"):
            current[k] = v
        else:  # prompt / variables / guard live under data
            current["data"][k] = v
    return save_entry(current)


def delete_entry(entry_id: str) -> bool:
    p = _path_for(entry_id)
    if not p.exists():
        return False
    p.unlink()
    return True


def node_for_id(entry_id: str) -> Optional[PromptNode]:
    """The stored entry as a compose ``PromptNode`` (``{prompt, variables}``), or None.
    The ``store=`` callable for resolving ``{"prompt_id": id}`` references.
    """
    entry = get_entry(entry_id)
    if entry is None:
        return None
    d = entry.get("data") or {}
    return {"prompt": d.get("prompt", ""), "variables": d.get("variables") or {}}


def upsert_envelope(env: dict) -> tuple[str, str]:
    """Write a prompt_pal envelope with its explicit ``id`` (packs/extend).

    Re-apply overwrites by ``(data.app, data.key)`` identity when present (keeping the
    existing file), else writes a new file at ``env.id``.
    """
    doc = _normalize(dict(env))
    d = doc.get("data") or {}
    existing = get_by_app_key(d.get("app"), d.get("key")) if d.get("key") else None
    if existing is not None:
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or doc["created_at"]
        save_entry(doc)
        return "updated", doc["id"]
    created = get_entry(doc["id"]) is not None
    save_entry(doc)
    return ("updated" if created else "created"), doc["id"]
