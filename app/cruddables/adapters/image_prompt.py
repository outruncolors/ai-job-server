"""Image-prompt adapter — wraps ``app.image_prompts`` (envelope-native store)."""

from __future__ import annotations

from app import image_prompts as store
from app.cruddables.base import CruddableAdapter
from app.cruddables.envelope import Cruddable, now_iso, slugify


class ImagePromptAdapter(CruddableAdapter):
    type_name = "image_prompt"
    label = "Image Prompts"

    def list_envelopes(self) -> list[Cruddable]:
        return [Cruddable(**d) for d in store.list_prompts()]

    def get_envelope(self, env_id: str) -> Cruddable | None:
        d = store.get_prompt(env_id)
        return Cruddable(**d) if d else None

    def upsert_envelope(self, env: Cruddable) -> tuple[str, str]:
        return store.upsert_envelope(env.model_dump())

    def delete(self, env_id: str) -> bool:
        return store.delete_prompt(env_id)

    def migrate_native(self, legacy: dict) -> dict:
        now = now_iso()
        return {
            "schema_version": 1,
            "type": self.type_name,
            "id": legacy.get("id") or slugify(legacy.get("name") or "image_prompt"),
            "name": legacy.get("name") or "",
            "description": legacy.get("description") or "",
            "tags": legacy.get("tags") or [],
            "created_at": legacy.get("created_at") or now,
            "updated_at": legacy.get("updated_at") or now,
            "data": {"prompt": legacy.get("prompt") or "", "workflow": legacy.get("workflow")},
        }
