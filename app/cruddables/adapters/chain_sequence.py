"""Chain-sequence adapter — wraps ``app.chain.sequences`` (envelope-native store).

The sequence content (`steps`/`variables`) lives under the envelope ``data`` along with a
``content_version`` (the step-graph schema version, distinct from the envelope's own
``schema_version``). ``upsert_envelope`` runs structural validation but skips capability
validation so cross-machine packs apply even when a named preset is absent locally.
"""

from __future__ import annotations

from app.chain import sequences as store
from app.cruddables.base import CruddableAdapter
from app.cruddables.envelope import Cruddable, now_iso, slugify


class ChainSequenceAdapter(CruddableAdapter):
    type_name = "chain_sequence"
    label = "Chain Sequences"

    def list_envelopes(self) -> list[Cruddable]:
        return [Cruddable(**d) for d in store.list_sequences()]

    def get_envelope(self, env_id: str) -> Cruddable | None:
        d = store.get_sequence(env_id)
        return Cruddable(**d) if d else None

    def upsert_envelope(self, env: Cruddable) -> tuple[str, str]:
        return store.upsert_envelope(env.model_dump())

    def delete(self, env_id: str) -> bool:
        return store.delete_sequence(env_id)

    def migrate_native(self, legacy: dict) -> dict:
        now = now_iso()
        return {
            "schema_version": 1,
            "type": self.type_name,
            "id": legacy.get("id") or slugify(legacy.get("name") or "sequence"),
            "name": legacy.get("name") or "",
            "description": legacy.get("description") or "",
            "tags": legacy.get("tags") or [],
            "created_at": legacy.get("created_at") or now,
            "updated_at": legacy.get("updated_at") or now,
            "data": {
                "content_version": legacy.get("schema_version") or store.SCHEMA_VERSION,
                "steps": legacy.get("steps") or [],
                "variables": legacy.get("variables") or [],
            },
        }
