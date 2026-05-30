"""HTTP surface for Hoodat (mounted at `/v1/apps/hoodat`).

Characters CRUD + per-field generation + avatar (generate/upload/serve) +
targeted exports. Text generation is not capability-gated (chain steps route to
the `llm` peer automatically). Avatar **generation** degrades gracefully: it
returns 503 on nodes without the `image` capability rather than gating the whole
app — upload and everything else stay available.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from ...server import get_local_capabilities
from . import avatars, characters_store, exports
from .generator import GenerationError, run_create, run_field
from .models import Character

router = APIRouter(prefix="/v1/apps/hoodat", tags=["hoodat"])


class CreateCharacterRequest(BaseModel):
    name: str
    prompt: str = ""


class RunExportRequest(BaseModel):
    detail: str = "standard"


def _summary(doc: dict) -> dict:
    return {
        "id": doc.get("id"),
        "name": doc.get("name"),
        "tagline": doc.get("tagline"),
        "summary": doc.get("summary"),
        "occupation": doc.get("occupation"),
        "avatar_path": doc.get("avatar_path"),
        "updated_at": doc.get("updated_at"),
    }


@router.get("/characters")
def list_characters():
    return {"characters": [_summary(d) for d in characters_store.list_characters()]}


@router.get("/characters/{character_id}")
def get_character(character_id: str):
    doc = characters_store.get_character(character_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return doc


@router.post("/characters", status_code=201)
async def create_character(body: CreateCharacterRequest):
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    try:
        character, job_id = await run_create(body.name, body.prompt)
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"character": character, "job_id": job_id}


@router.put("/characters/{character_id}")
def update_character(character_id: str, patch: dict):
    # Reject server-controlled keys in a patch.
    for protected in ("id", "schema_version", "created_at"):
        patch.pop(protected, None)
    try:
        updated = characters_store.update_character_fields(character_id, patch)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return updated


@router.delete("/characters/{character_id}")
def delete_character(character_id: str):
    img = avatars.avatar_file_if_exists(character_id)
    if not characters_store.delete_character(character_id):
        raise HTTPException(status_code=404, detail="Character not found")
    if img is not None:
        img.unlink()
    return {"ok": True}


@router.post("/characters/{character_id}/fields/{section}/{field}/generate")
async def generate_field(character_id: str, section: str, field: str):
    try:
        value, prompt_id, job_id = await run_field(character_id, section, field)
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"value": value, "prompt_id": prompt_id, "job_id": job_id}


@router.get("/characters/{character_id}/avatar")
def get_avatar(character_id: str):
    path = avatars.avatar_file_if_exists(character_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No avatar")
    return FileResponse(path, media_type="image/png")


@router.post("/characters/{character_id}/avatar/generate")
async def generate_avatar(character_id: str):
    if "image" not in get_local_capabilities():
        raise HTTPException(
            status_code=503,
            detail={"error": "capability_unavailable", "needed": "image",
                    "message": "image generation is not available on this node"},
        )
    try:
        url, job_id = await avatars.generate_avatar(character_id)
    except avatars.AvatarError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"avatar_url": url, "job_id": job_id}


@router.post("/characters/{character_id}/avatar/upload")
async def upload_avatar(character_id: str, file: UploadFile):
    data = await file.read()
    try:
        url = avatars.save_uploaded_avatar(character_id, data, file.content_type)
    except avatars.AvatarError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"avatar_url": url}


@router.get("/characters/{character_id}/exports")
def get_exports(character_id: str):
    if characters_store.get_character(character_id) is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"exports": exports.list_exports(), "detail_levels": list(exports.DETAIL_LEVELS)}


@router.post("/characters/{character_id}/exports/{export_key}/run")
async def run_export_endpoint(character_id: str, export_key: str, body: RunExportRequest):
    try:
        text, job_id = await exports.run_export(character_id, export_key, body.detail)
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"text": text, "job_id": job_id}
