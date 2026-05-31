"""Prattletale HTTP surface (prefix ``/v1/apps/prattletale``).

Conversation CRUD + the synchronous turn pipeline. A turn POST appends the user
turn, then runs the model turn **inline** via the generator (direct
``execute_chain_job``, not the shared ``JobQueue``) and returns both — the model
turn may be a ``system_error`` turn (still HTTP 200, rendered as an inline error
bubble). Retry re-runs the pipeline with the target turn excluded from context
and overwrites it **in place**, so the chat layout stays stable.

Mirrors Hoodat's router: ``APIRouter`` with the app prefix, Pydantic request
models, and ``404`` for missing resources.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..hoodat.characters_store import get_character
from . import settings_store, store
from .generator import run_model_turn
from .models import ConversationConfig, DeviceUser

router = APIRouter(prefix="/v1/apps/prattletale", tags=["prattletale"])


# --- request models --------------------------------------------------------

class ConversationCreate(BaseModel):
    title: str
    counterpart_character_id: str
    device_user: DeviceUser = Field(default_factory=DeviceUser)
    scenario: str = ""
    role_instructions: str = ""
    config: ConversationConfig = Field(default_factory=ConversationConfig)


class ConfigPatch(BaseModel):
    """Partial conversation ``config`` update (toggles). Unset fields are left alone."""

    voice_enabled: Optional[bool] = None
    typing_timing_enabled: Optional[bool] = None


class SettingsPatch(BaseModel):
    narrator_voice_preset_id: Optional[str] = None


class TurnItemIn(BaseModel):
    type: str
    text: str = ""


class TurnCreate(BaseModel):
    items: list[TurnItemIn]


# --- conversation CRUD -----------------------------------------------------

@router.get("/conversations")
def list_conversations():
    return {"conversations": store.list_conversations()}


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationCreate):
    if get_character(body.counterpart_character_id) is None:
        raise HTTPException(status_code=404, detail="Counterpart character not found")
    return store.create_conversation(body.model_dump())


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation, "transcript": store.get_transcript(conversation_id)}


@router.patch("/conversations/{conversation_id}")
def update_conversation_config(conversation_id: str, body: ConfigPatch):
    """Toggle the conversation's ``config`` flags (voice / typing timing) in place."""
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    config = dict(conversation.get("config") or {})
    config.update(body.model_dump(exclude_none=True))
    return store.update_conversation(conversation_id, {"config": config})


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str):
    if not store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/media/{filename}")
def get_media(conversation_id: str, filename: str):
    """Serve a generated audio file. ``filename`` must be a bare basename."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = store.media_file(conversation_id, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path, media_type="audio/wav")


# --- app-level settings (narrator voice) -----------------------------------

@router.get("/settings")
def get_settings():
    return settings_store.get_settings()


@router.put("/settings")
def put_settings(body: SettingsPatch):
    try:
        return settings_store.update_settings(body.model_dump())
    except settings_store.SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --- turns -----------------------------------------------------------------

@router.post("/conversations/{conversation_id}/turns")
async def create_turn(conversation_id: str, body: TurnCreate):
    user_turn = store.append_user_turn(
        conversation_id, [item.model_dump() for item in body.items]
    )
    if user_turn is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    model_turn, _ = await run_model_turn(conversation_id)
    return {"user_turn": user_turn, "model_turn": model_turn}


@router.post("/conversations/{conversation_id}/turns/{turn_id}/retry")
async def retry_turn(conversation_id: str, turn_id: str):
    transcript = store.get_transcript(conversation_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turns = transcript.get("turns", [])
    if not any(t.get("id") == turn_id for t in turns):
        raise HTTPException(status_code=404, detail="Turn not found")
    last = turns[-1]
    if last.get("id") != turn_id or last.get("author") != "model":
        raise HTTPException(status_code=409, detail="Only the latest model turn can be retried")
    model_turn, _ = await run_model_turn(conversation_id, replace_turn_id=turn_id)
    return model_turn
