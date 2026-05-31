"""Prompt Pal adapter — wraps ``app.prompt_pal.store`` (envelope-native store).

Identity is the logical ``(data.app, data.key)``; ``upsert_envelope`` overwrites by that
pair when present (so re-applying a pack restores the pack copy), else writes a new file.
Pack items namespace themselves by suffixing the *key* with ``_pack_<packid>``.
"""

from __future__ import annotations

from app.cruddables.base import CruddableAdapter
from app.cruddables.envelope import Cruddable, now_iso, slugify
from app.prompt_pal import store


class PromptPalAdapter(CruddableAdapter):
    type_name = "prompt_pal"
    label = "Prompt Pal Entries"

    def list_envelopes(self) -> list[Cruddable]:
        return [Cruddable(**d) for d in store.list_entries()]

    def get_envelope(self, env_id: str) -> Cruddable | None:
        d = store.get_entry(env_id)
        return Cruddable(**d) if d else None

    def upsert_envelope(self, env: Cruddable) -> tuple[str, str]:
        return store.upsert_envelope(env.model_dump())

    def delete(self, env_id: str) -> bool:
        return store.delete_entry(env_id)

    def migrate_native(self, legacy: dict) -> dict:
        now = now_iso()
        app = legacy.get("app") or store.DEFAULT_APP
        key = legacy.get("key") or ""
        return {
            "schema_version": 1,
            "type": self.type_name,
            "id": legacy.get("id") or slugify(f"{app}_{key}"),
            "name": legacy.get("title") or legacy.get("name") or "",
            "description": legacy.get("description") or "",
            "tags": legacy.get("tags") or [],
            "created_at": legacy.get("created_at") or now,
            "updated_at": legacy.get("updated_at") or now,
            "data": {
                "app": app,
                "key": key,
                "prompt": legacy.get("prompt") or "",
                "variables": legacy.get("variables") or {},
                "guard": legacy.get("guard"),
            },
        }
