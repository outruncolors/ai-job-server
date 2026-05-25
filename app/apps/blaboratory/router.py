"""HTTP surface for Blaboratory (mounted at `/v1/apps/blaboratory`).

- `GET  /rooms`                       → all 16 rooms with a thin occupant summary
- `GET  /residents`                   → all residents (debug)
- `GET  /residents/{id}`              → full Resident (404 if missing)
- `POST /rooms/{room_id}/residents`   → generate + place a resident
    body: `{ mode: "free_text"|"guided", free_text?, fields? }`
    201 on success; 409 if the room is occupied; 422 on a bad body;
    502 if generation fails after retries.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import residents_store, rooms
from .generator import GenerationError, run_generation

router = APIRouter(prefix="/v1/apps/blaboratory", tags=["blaboratory"])


class CreateResidentRequest(BaseModel):
    mode: Literal["free_text", "guided"]
    free_text: Optional[str] = None
    fields: Optional[dict] = None


def _occupant_summary(resident_id: Optional[str]) -> Optional[dict]:
    if resident_id is None:
        return None
    resident = residents_store.get_resident(resident_id)
    if resident is None:
        # Dangling occupancy (resident deleted out from under it) — treat as empty.
        return None
    return {
        "id": resident["id"],
        "name": resident["name"],
        "occupation": resident["occupation"],
        "age": resident["age"],
    }


@router.get("/rooms")
async def get_rooms() -> dict:
    occ = rooms.list_occupancy()
    return {
        "rooms": [
            {"room_id": rid, "occupant": _occupant_summary(occ[str(rid)])}
            for rid in rooms.ROOM_IDS
        ]
    }


@router.get("/residents")
async def get_residents() -> dict:
    return {"residents": residents_store.list_residents()}


@router.get("/residents/{resident_id}")
async def get_resident(resident_id: str) -> dict:
    resident = residents_store.get_resident(resident_id)
    if resident is None:
        raise HTTPException(status_code=404, detail="resident not found")
    return resident


@router.post("/rooms/{room_id}/residents", status_code=201)
async def create_resident_in_room(room_id: int, body: CreateResidentRequest) -> dict:
    if room_id not in rooms.ROOM_IDS:
        raise HTTPException(status_code=422, detail="room_id must be 1–16")
    if body.mode == "free_text" and not (body.free_text and body.free_text.strip()):
        raise HTTPException(status_code=422, detail="free_text is required in free_text mode")
    if not rooms.is_empty(room_id):
        raise HTTPException(status_code=409, detail=f"room {room_id} is already occupied")

    try:
        resident, job_id = await run_generation(
            room_id=room_id,
            mode=body.mode,
            free_text=body.free_text,
            fields=body.fields,
        )
    except GenerationError as exc:
        # Re-check occupancy so a race that filled the room reports 409, not 502.
        if not rooms.is_empty(room_id):
            raise HTTPException(status_code=409, detail=str(exc))
        raise HTTPException(status_code=502, detail=f"generation failed: {exc}")

    return {"resident": resident, "room_id": room_id, "job_id": job_id}
