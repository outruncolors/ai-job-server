"""Tomeberry template adapter — global starter templates for tales.

Wraps ``app.apps.tomeberry.templates_store`` (envelope-native). Applying a Pack of
``tomeberry_template`` envelopes makes them available globally; a tale then copies
one into its own ``concepts/`` via ``POST /apply-template`` (the copy, not the
global, is what the tale edits).
"""

from __future__ import annotations

from app.cruddables.base import CruddableAdapter
from app.cruddables.envelope import Cruddable, now_iso, slugify


class TomeberryTemplateAdapter(CruddableAdapter):
    type_name = "tomeberry_template"
    label = "Tomeberry Templates"

    def _store(self):
        from app.apps.tomeberry import templates_store

        return templates_store

    def list_envelopes(self) -> list[Cruddable]:
        return [Cruddable(**d) for d in self._store().list_templates()]

    def get_envelope(self, env_id: str) -> Cruddable | None:
        d = self._store().get_template(env_id)
        return Cruddable(**d) if d else None

    def upsert_envelope(self, env: Cruddable) -> tuple[str, str]:
        return self._store().upsert_envelope(env.model_dump())

    def delete(self, env_id: str) -> bool:
        return self._store().delete_template(env_id)

    def migrate_native(self, legacy: dict) -> dict:
        now = now_iso()
        return {
            "schema_version": 1,
            "type": self.type_name,
            "id": legacy.get("id") or slugify(legacy.get("name") or "template"),
            "name": legacy.get("name") or "",
            "description": legacy.get("description") or "",
            "tags": legacy.get("tags") or [],
            "created_at": legacy.get("created_at") or now,
            "updated_at": legacy.get("updated_at") or now,
            "data": legacy.get("data") or {"concepts": []},
        }
