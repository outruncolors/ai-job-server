"""File-per-document store for Hoodat characters — unified Cruddable envelope.

On disk each character is its own JSON file at ``config/hoodat/characters/<id>.json``
in the shared envelope shape::

    {schema_version:1, type:"hoodat_character", id, name, description, tags,
     created_at, updated_at, data:{<character body> + content_version}}

The nested character *body* (summary/appearance/personality/… everything the
:class:`Character` model owns) lives under ``data``; the body's own schema version
travels as ``data.content_version`` (distinct from the envelope's
``schema_version``). ``id`` is a human-readable slug derived from the name and is the
filename.

The store is the **envelope boundary**: the flat-body API
(:func:`get_character` / :func:`list_characters` / :func:`create_character` /
:func:`save_character` / :func:`update_character_fields` / :func:`delete_character`)
still accepts and returns the flat :class:`Character` document (``id`` / timestamps /
``schema_version`` at the top level, nested blocks beside them), so the router,
generator, avatars, exports, and the profile UI are unchanged. The envelope API
(:func:`list_envelopes` / :func:`get_envelope` / :func:`upsert_envelope`) backs the
Cruddable adapter / Packs.

Legacy (pre-envelope) flat docs *and* legacy v1 ``Appearance`` shapes are tolerated on
read; the authoritative re-slug migration lives in ``app.cruddables.migrate``.
``id`` / ``schema_version`` / timestamps are assigned here, never by callers or the LLM.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app.cruddables.envelope import now_iso, slugify, unique_id

from .models import Character

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHARACTERS_DIR: Path = PROJECT_ROOT / "config" / "hoodat" / "characters"

TYPE_NAME = "hoodat_character"
# Version of the *character body* shape (nested blocks), stored inside `data`.
# Distinct from the envelope's own top-level `schema_version`.
CONTENT_VERSION = 2

# Sections that are nested blocks (vs `identity`, which is top-level fields).
_NESTED_SECTIONS = {"appearance", "personality", "background", "speaking_style"}

# Body keys that map onto envelope meta columns rather than the `data` payload.
_META_KEYS = ("id", "schema_version", "created_at", "updated_at", "name")


def _now_iso() -> str:
    return now_iso()


def _path_for(character_id: str) -> Path:
    return CHARACTERS_DIR / f"{character_id}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _taken_ids() -> set[str]:
    if not CHARACTERS_DIR.exists():
        return set()
    return {p.stem for p in CHARACTERS_DIR.glob("*.json")}


# --- envelope <-> body conversion ------------------------------------------

def _normalize_body(doc: dict) -> dict:
    """Return a flat character body in the current (v2) shape, migrating legacy v1.

    Old docs carry `schema_version < 2` and the flat `Appearance` fields
    (`hair`/`eyes`/`primary_outfit`). Round-tripping through `Character` runs the
    `Appearance` before-validator and fills new defaults, so callers never see the
    legacy shape. We drop the old `schema_version` first (its `Literal[2]` would
    reject `1`). Falls back to the raw doc if validation fails so a malformed legacy
    doc degrades rather than 500ing.
    """
    if doc.get("schema_version", 1) >= 2:
        return doc
    try:
        legacy = {k: v for k, v in doc.items() if k != "schema_version"}
        return Character(**legacy).model_dump()
    except Exception:  # noqa: BLE001 — best-effort read migration
        return doc


def _to_envelope(
    body: dict,
    *,
    tags: Optional[list] = None,
    description: Optional[str] = None,
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> dict:
    """Wrap a flat (validated) character body into an on-disk envelope.

    The body's own version becomes ``data.content_version``. ``description`` defaults
    to the character's summary; ``tags`` default to empty (the body model carries
    neither, so callers thread them through to preserve pack/user assignments).
    """
    now = _now_iso()
    data = {k: v for k, v in body.items() if k not in _META_KEYS}
    data["content_version"] = body.get("schema_version") or CONTENT_VERSION
    return {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": body.get("id"),
        "name": body.get("name") or "",
        "description": description if description is not None else (body.get("summary") or ""),
        "tags": list(tags or []),
        "created_at": created_at or body.get("created_at") or now,
        "updated_at": updated_at or body.get("updated_at") or now,
        "data": data,
    }


def _body_from_envelope(env: dict) -> dict:
    """Reconstruct a flat character body dict from an envelope doc."""
    data = dict(env.get("data") or {})
    content_version = data.pop("content_version", CONTENT_VERSION)
    return {
        "id": env.get("id"),
        "schema_version": content_version,
        "created_at": env.get("created_at"),
        "updated_at": env.get("updated_at"),
        "name": env.get("name") or data.get("name") or "",
        **{k: v for k, v in data.items() if k != "name"},
    }


def _to_body(doc: dict) -> dict:
    """Flat, normalized (v2) character body from an envelope OR a legacy flat doc."""
    if doc.get("type") == TYPE_NAME and isinstance(doc.get("data"), dict):
        body = _body_from_envelope(doc)
    else:
        body = dict(doc)
    return _normalize_body(body)


def _read_envelope(doc: dict) -> dict:
    """An on-disk doc as an envelope, migrating a legacy flat character if needed."""
    if doc.get("type") == TYPE_NAME and isinstance(doc.get("data"), dict):
        doc.setdefault("tags", [])
        doc.setdefault("description", "")
        return doc
    return _to_envelope(_normalize_body(dict(doc)))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- flat-body API (router / generator / avatars / exports / UI) -----------

def list_characters() -> list[dict]:
    """All persisted characters as flat bodies (unordered)."""
    if not CHARACTERS_DIR.exists():
        return []
    return [_to_body(_load(p)) for p in CHARACTERS_DIR.glob("*.json")]


def get_character(character_id: str) -> Optional[dict]:
    p = _path_for(character_id)
    if not p.exists():
        return None
    return _to_body(_load(p))


def create_character(fields: dict) -> dict:
    """Build a new character from `fields`, assigning server-controlled fields
    (`id` slug, `schema_version=2`, timestamps), validating against `Character`, and
    persisting it as an envelope. Returns the flat body.
    """
    now = _now_iso()
    doc = dict(fields)
    doc["id"] = unique_id(slugify(doc.get("name") or "character"), _taken_ids())
    doc["schema_version"] = 2
    doc["created_at"] = now
    doc["updated_at"] = now
    character = Character(**doc)
    data = character.model_dump()
    _atomic_write(_path_for(character.id), _to_envelope(data))
    return data


def save_character(character: dict) -> dict:
    """Persist an existing character (flat body), bumping `updated_at`. Preserves the
    on-disk envelope's `tags` (the body model does not carry them)."""
    if not character.get("id"):
        raise ValueError("character must have an id to save")
    doc = dict(character)
    doc["updated_at"] = _now_iso()
    validated = Character(**doc)
    data = validated.model_dump()
    prior_tags = (get_envelope(validated.id) or {}).get("tags") or []
    _atomic_write(_path_for(validated.id), _to_envelope(data, tags=prior_tags))
    return data


def update_character_fields(character_id: str, patch: dict) -> Optional[dict]:
    """Deep-merge a nested `patch` into the character and persist.

    `patch` may carry top-level identity fields and/or per-section sub-dicts
    (e.g. `{"name": "...", "appearance": {"hair_color": "..."}}`). None if the
    character is missing.
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


# --- envelope API (Cruddable adapter / Packs) ------------------------------

def list_envelopes() -> list[dict]:
    if not CHARACTERS_DIR.exists():
        return []
    return [_read_envelope(_load(p)) for p in CHARACTERS_DIR.glob("*.json")]


def get_envelope(character_id: str) -> Optional[dict]:
    p = _path_for(character_id)
    if not p.exists():
        return None
    return _read_envelope(_load(p))


def upsert_envelope(env: dict) -> tuple[str, str]:
    """Write a hoodat_character envelope with its explicit ``id`` (packs/extend).

    Validates the body via :class:`Character`, preserves an existing row's
    ``created_at``, and keeps the envelope's ``tags`` / ``description``. Returns
    ``("created"|"updated", id)``.
    """
    if not env.get("id"):
        raise ValueError("envelope must have an id")
    existing = get_envelope(env["id"])
    now = _now_iso()
    body = _to_body(env)
    body["id"] = env["id"]
    body["schema_version"] = 2
    body["created_at"] = (existing or {}).get("created_at") or env.get("created_at") or now
    body["updated_at"] = now
    validated = Character(**body)
    data = validated.model_dump()
    out = _to_envelope(
        data,
        tags=env.get("tags"),
        description=env.get("description"),
        created_at=body["created_at"],
        updated_at=now,
    )
    _atomic_write(_path_for(validated.id), out)
    return ("updated" if existing else "created"), validated.id
