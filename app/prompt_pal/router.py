"""HTTP surface for Prompt Pal (mounted at `/v1/prompt-pal`).

- `GET    /entries`            → all entries (optional `?app=` / `?tag=` filter)
- `GET    /entries/{id}`       → one entry (404 if missing)
- `POST   /entries`            → create an ad-hoc entry (409 on duplicate (app,key))
- `PUT    /entries/{id}`       → patch editable fields (422 / 404)
- `DELETE /entries/{id}`       → delete (404 if missing)
- `POST   /entries/{id}/preview` → compose with supplied variables (editor preview)

Pure config CRUD — not capability-gated.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import store
from .compose import PromptCompositionError, compose
from .models import PromptEntryPatch

router = APIRouter(prefix="/v1/prompt-pal", tags=["prompt-pal"])


class CreateEntryRequest(BaseModel):
    app: str
    key: str
    title: str
    prompt: str = ""
    description: str = ""
    tags: list[str] = []
    variables: dict[str, Any] = {}


class PreviewRequest(BaseModel):
    variables: dict[str, Any] = {}


@router.get("/entries")
def list_entries(app: Optional[str] = None, tag: Optional[str] = None):
    entries = store.list_entries()
    if app:
        entries = [e for e in entries if e.get("app") == app]
    if tag:
        entries = [e for e in entries if tag in (e.get("tags") or [])]
    return {"entries": entries}


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str):
    entry = store.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Prompt entry not found")
    return entry


@router.post("/entries", status_code=201)
def create_entry(body: CreateEntryRequest):
    if store.get_by_app_key(body.app, body.key) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"prompt ({body.app!r}, {body.key!r}) already exists",
        )
    return store.create_entry(body.model_dump())


@router.put("/entries/{entry_id}")
def update_entry(entry_id: str, patch: PromptEntryPatch):
    updated = store.update_entry(entry_id, **patch.model_dump(exclude_none=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Prompt entry not found")
    return updated


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str):
    if not store.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Prompt entry not found")
    return {"ok": True}


@router.post("/entries/{entry_id}/preview")
def preview_entry(entry_id: str, body: PreviewRequest):
    entry = store.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Prompt entry not found")
    node = {
        "prompt": entry.get("prompt", ""),
        "variables": {**(entry.get("variables") or {}), **body.variables},
    }
    try:
        text = compose(node, store=store.node_for_id)
    except PromptCompositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"text": text}
