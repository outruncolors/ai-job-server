"""The ``CruddableAdapter`` interface — a uniform surface over each domain store.

Adapters are thin: the domain store modules (``app/wildcards.py`` etc.) own the actual
files and persist envelope-shaped docs after the migration. An adapter exposes the
uniform operations Packs and the Cruddables page need, converting between the store's
dicts and :class:`Cruddable`, and knows how to reshape a *legacy* (pre-envelope) doc via
:meth:`migrate_native` (used by the one-time migration and read-time normalization).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .envelope import Cruddable


class CruddableAdapter(ABC):
    #: registry key / "table" name, e.g. ``"wildcard"``
    type_name: str
    #: human label for the UI, e.g. ``"Wildcards"``
    label: str

    @abstractmethod
    def list_envelopes(self) -> list[Cruddable]:
        """All entities of this type, as envelopes (newest store order)."""

    @abstractmethod
    def get_envelope(self, env_id: str) -> Cruddable | None:
        """One entity by id, or None."""

    @abstractmethod
    def upsert_envelope(self, env: Cruddable) -> tuple[str, str]:
        """Write ``env`` with its explicit ``env.id``.

        Returns ``("created", id)`` or ``("updated", id)``. Preserves ``created_at`` of an
        existing row and stamps ``updated_at``. Used by both pack-apply and extend.
        """

    @abstractmethod
    def delete(self, env_id: str) -> bool:
        """Delete by id; True if it existed."""

    def count(self) -> int:
        return len(self.list_envelopes())

    @abstractmethod
    def migrate_native(self, legacy: dict) -> dict:
        """Reshape one *legacy* (pre-envelope) doc into an envelope dict.

        Re-slugs the id from the name and moves type-specific fields under ``data``. Pure
        (no I/O); the caller persists and is responsible for id-uniqueness/reference fixes.
        """
