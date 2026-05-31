"""HTTP routes for browsing and applying packs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import service, store

router = APIRouter(prefix="/v1/packs", tags=["packs"])


@router.get("/packs")
def list_packs() -> dict:
    return {"packs": store.list_packs()}


@router.get("/{type_name}/{pack_id}")
def get_pack(type_name: str, pack_id: str) -> dict:
    pack = store.get_pack(type_name, pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="pack not found")
    return pack


@router.post("/{type_name}/{pack_id}/apply")
def apply_pack(type_name: str, pack_id: str) -> dict:
    try:
        return service.apply_pack(type_name, pack_id)
    except service.PackNotFound:
        raise HTTPException(status_code=404, detail="pack not found")
