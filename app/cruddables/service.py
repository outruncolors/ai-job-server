"""Shared apply/extend service — the single code path behind pack-apply and the
Cruddables "Extend" action. Routes each item by its own ``type`` to the right adapter.
One bad item never aborts the rest.
"""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from .envelope import Cruddable
from .registry import get_adapter


def apply_items(items: list[dict], *, expected_type: Optional[str] = None) -> dict:
    """Upsert each envelope in ``items``.

    ``expected_type`` (the Cruddables page's per-type panel) is a guard only: an item
    whose ``type`` differs is reported as an error rather than written.
    Returns ``{created,updated,errored,results:[{id,type,name,status,error?}]}``.
    """
    results: list[dict] = []
    for raw in items or []:
        rid = raw.get("id") if isinstance(raw, dict) else None
        rtype = raw.get("type") if isinstance(raw, dict) else None
        try:
            env = Cruddable(**raw)
        except ValidationError as exc:
            results.append({"id": rid, "type": rtype, "status": "error",
                            "error": f"invalid envelope: {exc.errors()[:3]}"})
            continue
        if expected_type and env.type != expected_type:
            results.append({"id": env.id, "type": env.type, "name": env.name,
                            "status": "error",
                            "error": f"type mismatch: expected {expected_type!r}"})
            continue
        adapter = get_adapter(env.type)
        if adapter is None:
            results.append({"id": env.id, "type": env.type, "name": env.name,
                            "status": "error", "error": f"unknown type {env.type!r}"})
            continue
        try:
            action, eid = adapter.upsert_envelope(env)
            results.append({"id": eid, "type": env.type, "name": env.name,
                            "status": action})
        except Exception as exc:  # noqa: BLE001 — surface per-item, never abort batch
            results.append({"id": env.id, "type": env.type, "name": env.name,
                            "status": "error", "error": str(exc)})
    return {
        "created": sum(1 for r in results if r["status"] == "created"),
        "updated": sum(1 for r in results if r["status"] == "updated"),
        "errored": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }
