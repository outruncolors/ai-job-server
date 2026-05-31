"""Cruddables HTTP surface — `/v1/cruddables`.

Powers the Manage → Cruddables page: list types with counts, export a type's collection
as an envelope array, and extend a collection from a pasted/uploaded envelope array.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .registry import get_adapter, list_types
from .service import apply_items

router = APIRouter(prefix="/v1/cruddables", tags=["cruddables"])


@router.get("/types")
async def get_types() -> dict:
    return {"types": list_types()}


@router.get("/{type_name}/export")
async def export_type(type_name: str) -> list:
    adapter = get_adapter(type_name)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"unknown type {type_name!r}")
    return [e.model_dump() for e in adapter.list_envelopes()]


@router.post("/{type_name}/extend")
async def extend_type(type_name: str, items: list[dict] = Body(...)) -> dict:
    if get_adapter(type_name) is None:
        raise HTTPException(status_code=404, detail=f"unknown type {type_name!r}")
    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="body must be a JSON array of envelopes")
    return apply_items(items, expected_type=type_name)
