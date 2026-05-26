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

from . import (
    context_pipeline,
    event_store,
    residents_store,
    rooms,
    sim_clock,
    tick_runner,
    utterance_store,
)
from .generator import GenerationError, run_generation

router = APIRouter(prefix="/v1/apps/blaboratory", tags=["blaboratory"])

# Map an action name to the single word shown on its room's grid cell.
_ACTION_WORD = {
    "use_computer": "computer",
    "use_televisor": "televisor",
    "use_speakerphone": "phone",
    "sleep": "asleep",
    "idle": "idle",
}


def _action_word(action: Optional[str]) -> Optional[str]:
    if not action:
        return None
    return _ACTION_WORD.get(action, action)


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


# ---- simulation: timeline / events / clock -------------------------------


@router.get("/ticks/latest")
async def get_latest_tick() -> dict:
    return {"tick": event_store.max_tick()}


@router.get("/ticks/{tick}/rooms")
async def get_rooms_at_tick(tick: int) -> dict:
    """Per-room most-recent-action word at/under ``tick`` (master grid)."""
    occ = rooms.list_occupancy()
    out = []
    for rid in rooms.ROOM_IDS:
        occupant = _occupant_summary(occ[str(rid)])
        word = None
        if occupant is not None:
            ev = event_store.latest_event_for_room(rid, until_tick=tick)
            word = _action_word(ev["action"]) if ev else None
        out.append({"room_id": rid, "occupant": occupant, "action_word": word})
    return {"tick": tick, "rooms": out}


@router.get("/residents/{resident_id}/events")
async def get_resident_events(resident_id: str, until_tick: Optional[int] = None) -> dict:
    """A resident's event log, newest-first, truncated at the playhead."""
    if residents_store.get_resident(resident_id) is None:
        raise HTTPException(status_code=404, detail="resident not found")
    return {
        "resident_id": resident_id,
        "until_tick": until_tick,
        "events": event_store.events_for_resident(resident_id, until_tick=until_tick),
    }


@router.get("/residents/{resident_id}/context")
async def get_resident_context(resident_id: str, tick: Optional[int] = None) -> dict:
    """The resident's active context/knowledge block (debug/inspection)."""
    resident = residents_store.get_resident(resident_id)
    if resident is None:
        raise HTTPException(status_code=404, detail="resident not found")
    t = tick if tick is not None else event_store.max_tick()
    context = await context_pipeline.build_context(resident, tick=t)
    return {"resident_id": resident_id, "tick": t, "context": context}


@router.get("/rooms/{room_id}/utterances")
async def get_room_utterances(room_id: int, until_tick: Optional[int] = None) -> dict:
    """Phone-call lines surfaced in a room (newest-first, truncated at playhead)."""
    if room_id not in rooms.ROOM_IDS:
        raise HTTPException(status_code=422, detail="room_id must be 1–16")
    return {
        "room_id": room_id,
        "utterances": utterance_store.utterances_for_room(room_id, until_tick=until_tick),
    }


@router.post("/ticks/fire")
async def fire_tick_now() -> dict:
    """Manually fire one tick now (runs on the LOW background lane)."""
    tick = tick_runner.next_tick()
    job_id = await sim_clock.fire_tick(tick)
    return {"tick": tick, "job_id": job_id}


@router.get("/clock")
async def get_clock() -> dict:
    return {"running": sim_clock.get_sim_clock().running}


@router.post("/clock/{command}")
async def control_clock(command: Literal["start", "stop"]) -> dict:
    clock = sim_clock.get_sim_clock()
    if command == "start":
        await clock.start()
    else:
        await clock.stop()
    return {"running": clock.running}
