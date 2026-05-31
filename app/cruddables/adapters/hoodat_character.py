"""Hoodat-character adapter — wraps ``app.apps.hoodat.characters_store``.

The store is the envelope boundary: it persists the unified envelope on disk (the
nested :class:`~app.apps.hoodat.models.Character` body lives under ``data`` with a
``content_version``) while keeping a flat-body API for the rest of the app. This
adapter speaks only the store's envelope API (``list_envelopes`` /
``get_envelope`` / ``upsert_envelope``) so Packs / Cruddables see envelopes.
"""

from __future__ import annotations

from app.apps.hoodat import characters_store as store
from app.cruddables.base import CruddableAdapter
from app.cruddables.envelope import Cruddable, now_iso, slugify


class HoodatCharacterAdapter(CruddableAdapter):
    type_name = "hoodat_character"
    label = "Hoodat Characters"

    def list_envelopes(self) -> list[Cruddable]:
        return [Cruddable(**e) for e in store.list_envelopes()]

    def get_envelope(self, env_id: str) -> Cruddable | None:
        e = store.get_envelope(env_id)
        return Cruddable(**e) if e else None

    def upsert_envelope(self, env: Cruddable) -> tuple[str, str]:
        return store.upsert_envelope(env.model_dump())

    def delete(self, env_id: str) -> bool:
        return store.delete_character(env_id)

    def migrate_native(self, legacy: dict) -> dict:
        now = now_iso()
        body = store._normalize_body(dict(legacy))
        data = {
            k: v
            for k, v in body.items()
            if k not in ("id", "schema_version", "created_at", "updated_at", "name")
        }
        data["content_version"] = body.get("schema_version") or store.CONTENT_VERSION
        return {
            "schema_version": 1,
            "type": self.type_name,
            "id": legacy.get("id") or slugify(legacy.get("name") or "character"),
            "name": legacy.get("name") or "",
            "description": legacy.get("description") or body.get("summary") or "",
            "tags": legacy.get("tags") or [],
            "created_at": legacy.get("created_at") or now,
            "updated_at": legacy.get("updated_at") or now,
            "data": data,
        }
