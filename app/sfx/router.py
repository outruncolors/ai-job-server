"""HTTP routes for browsing SFX packs and serving clips."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import store
from .models import Identity, identity_label

router = APIRouter(prefix="/v1/sfx", tags=["sfx"])

_MEDIA_TYPES = {".wav": "audio/wav", ".ogg": "audio/ogg", ".mp3": "audio/mpeg"}


@router.get("/packs")
def list_packs() -> dict:
    return {"packs": [p.model_dump() for p in store.list_packs()]}


@router.get("/identities")
def list_identities() -> dict:
    """Selectable identity profiles (base + pitch variants) across installed
    identity packs, for the Hoodat dropdown. Falls back to the base enum when no
    identity pack is installed so the control is never empty."""
    profiles = store.list_identity_profiles()
    if not profiles:
        profiles = [{"value": i.value, "label": identity_label(i.value),
                     "pitch": "base", "packs": []} for i in Identity]
    return {"identities": profiles}


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str) -> dict:
    pack = store.get_pack(pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="sfx pack not found")
    return pack.model_dump()


@router.get("/packs/{pack_id}/profiles/{profile_id}")
def get_profile(pack_id: str, profile_id: str) -> dict:
    profile = store.get_profile(pack_id, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="sfx profile not found")
    return {"profile": profile.model_dump(), "categories": store.category_summary(profile)}


class PreviewRequest(BaseModel):
    pack_id: str
    profile_id: str
    category: str | None = None
    effect_id: str | None = None


@router.post("/preview")
def preview(req: PreviewRequest) -> dict:
    """Pick one clip (explicit effect_id, else weighted-random in category) and
    return a served URL so the UI can audition it."""
    profile = store.get_profile(req.pack_id, req.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="sfx profile not found")
    item = None
    if req.effect_id:
        item = next((it for it in profile.items if it.id == req.effect_id), None)
    elif req.category:
        item = store.weighted_choice(store.items_in_category(profile, req.category))
    else:
        item = store.weighted_choice(profile.items)
    if item is None:
        raise HTTPException(status_code=404, detail="no matching effect")
    return {"effect_id": item.id, "duration_ms": item.duration_ms,
            "url": f"/v1/sfx/file/{item.path}"}


@router.get("/file/{rel_path:path}")
def get_file(rel_path: str):
    path = store.resolve_file_path(rel_path)
    if path is None:
        raise HTTPException(status_code=404, detail="sfx file not found")
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"))
