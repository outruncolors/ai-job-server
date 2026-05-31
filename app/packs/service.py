"""Applying a pack == extending the cruddable stores with the pack's items."""

from __future__ import annotations

from ..cruddables import service as cruddables_service
from . import store


class PackNotFound(Exception):
    pass


def apply_pack(type_name: str, pack_id: str) -> dict:
    """Apply a pack by routing its items through the shared cruddable upsert.

    Items are fully-formed envelopes; each is routed by its own ``type`` field,
    so a pack whose items target one type still applies through the same path as
    a hand-pasted Extend. Returns the ``apply_items`` report.
    """
    pack = store.get_pack(type_name, pack_id)
    if pack is None:
        raise PackNotFound(f"{type_name}/{pack_id}")
    items = pack.get("items") or []
    report = cruddables_service.apply_items(items)
    report["pack"] = {"id": pack.get("id"), "type": type_name}
    return report
