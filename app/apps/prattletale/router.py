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

import json
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...cruddables.envelope import now_iso
from ...prompt_pal import service as pp_service
from ...prompt_pal import store as pp_store
from ..hoodat.characters_store import get_character
from . import settings_store, store, voice
from .generator import PRATTLETALE_PROMPT_VERSION, GenerationError, run_model_turn
from .models import ConversationConfig, DeviceUser, DialogueFeel
from .plugins import registry as plugin_registry

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
    """Partial conversation ``config`` update. Unset fields are left alone."""

    context_window_turns: Optional[int] = None
    voice_enabled: Optional[bool] = None
    typing_timing_enabled: Optional[bool] = None
    variety_pass_enabled: Optional[bool] = None
    structured_chat_history: Optional[bool] = None
    director_enabled: Optional[bool] = None
    repair_enabled: Optional[bool] = None
    debug_prattletale: Optional[bool] = None
    enabled_plugins: Optional[list[str]] = None
    sfx_enabled: Optional[bool] = None
    sfx_chance: Optional[float] = None
    sfx_domains: Optional[list[str]] = None
    dialogue_feel_enabled: Optional[bool] = None
    dialogue_feel_roll_enabled: Optional[bool] = None
    dialogue_feel_director_enabled: Optional[bool] = None
    # Full replace of the override block (the frontend sends the whole object).
    dialogue_feel: Optional[DialogueFeel] = None


class ConversationUpdate(ConfigPatch):
    """Broadened conversation ``PATCH`` body (SP2): editable metadata + behaviour.

    Inherits the flat config keys from :class:`ConfigPatch` (so the Phase-1
    frontend's flat ``{voice_enabled: …}`` toggles keep working — they're hoisted
    into ``config``) and also accepts a nested ``config`` patch. All fields are
    optional; only those set are applied.
    """

    title: Optional[str] = None
    scenario: Optional[str] = None
    role_instructions: Optional[str] = None
    device_user: Optional[DeviceUser] = None
    config: Optional[ConfigPatch] = None


class SettingsPatch(BaseModel):
    narrator_voice_preset_id: Optional[str] = None


class ItemPatch(BaseModel):
    """In-place edit of one transcript item (SP1). Unset fields are left alone."""

    text: Optional[str] = None
    hidden_from_context: Optional[bool] = None


class TurnItemIn(BaseModel):
    type: str
    text: str = ""


class TurnCreate(BaseModel):
    items: list[TurnItemIn]


class VersionSelect(BaseModel):
    """Pick which generated version of a turn is active (regenerate nav)."""

    index: int


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
def update_conversation_config(conversation_id: str, body: ConversationUpdate):
    """Edit a conversation's metadata (``title``/``scenario``/``role_instructions``/
    ``device_user``) and/or behaviour ``config`` in place.

    Config can be supplied nested (``{config: {context_window_turns: …}}``) or as
    flat back-compat keys (``{voice_enabled: …}``, hoisted into ``config``); the
    nested form wins on conflict. Unset config keys are preserved (deep merge).
    """
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Hoist flat config keys, then layer the nested config patch on top.
    config_patch = ConfigPatch(
        **{k: getattr(body, k) for k in ConfigPatch.model_fields}
    ).model_dump(exclude_none=True)
    if body.config is not None:
        config_patch.update(body.config.model_dump(exclude_none=True))

    if "context_window_turns" in config_patch and config_patch["context_window_turns"] < 1:
        raise HTTPException(status_code=422, detail="context_window_turns must be >= 1")

    patch: dict = {}
    for field in ("title", "scenario", "role_instructions"):
        value = getattr(body, field)
        if value is not None:
            patch[field] = value
    if body.device_user is not None:
        patch["device_user"] = body.device_user.model_dump()
    if config_patch:
        config = dict(conversation.get("config") or {})
        config.update(config_patch)
        patch["config"] = config

    if not patch:
        return conversation
    return store.update_conversation(conversation_id, patch)


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
    # Don't synthesize here: the response returns text immediately and the client
    # synthesizes each message lazily (POST .../items/{item_id}/audio) so playback
    # of message 1 isn't blocked on synthesizing the whole reply.
    model_turn, _ = await run_model_turn(conversation_id, synthesize=False)
    return {"user_turn": user_turn, "model_turn": model_turn}


@router.post("/conversations/{conversation_id}/continue")
async def continue_turn(conversation_id: str):
    """Have the partner take another turn with no user input.

    Runs the model-turn pipeline against the current transcript without appending
    a user turn first — used when the composer is empty (the "Continue" button) and
    to let the character open an empty conversation. Like :func:`create_turn`, a
    model-side failure comes back as a 200 ``system_error`` turn.
    """
    if store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    model_turn, _ = await run_model_turn(conversation_id, synthesize=False)
    return {"model_turn": model_turn}


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
    model_turn, _ = await run_model_turn(conversation_id, replace_turn_id=turn_id, synthesize=False)
    return model_turn


@router.post("/conversations/{conversation_id}/turns/{turn_id}/regenerate")
async def regenerate_turn(conversation_id: str, turn_id: str):
    """Generate a fresh **version** of the latest model turn, keeping the prior
    one(s) so the user can flip between them. Like Retry, only the latest model
    turn is eligible (409 otherwise); unlike Retry it appends rather than
    overwrites. A failed regenerate leaves the turn intact and returns 502.
    """
    transcript = store.get_transcript(conversation_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turns = transcript.get("turns", [])
    if not any(t.get("id") == turn_id for t in turns):
        raise HTTPException(status_code=404, detail="Turn not found")
    last = turns[-1]
    if last.get("id") != turn_id or last.get("author") != "model":
        raise HTTPException(status_code=409, detail="Only the latest model turn can be regenerated")
    try:
        model_turn, _ = await run_model_turn(
            conversation_id, add_version_turn_id=turn_id, synthesize=False
        )
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return model_turn


@router.post("/conversations/{conversation_id}/turns/{turn_id}/version")
def select_turn_version(conversation_id: str, turn_id: str, body: VersionSelect):
    """Switch which generated version of a turn is active (the regenerate nav).

    Works on any turn that has versions, regardless of position. 404 when the
    conversation or turn is missing; 422 when the turn isn't versioned or the
    index is out of range.
    """
    transcript = store.get_transcript(conversation_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not any(t.get("id") == turn_id for t in transcript.get("turns", [])):
        raise HTTPException(status_code=404, detail="Turn not found")
    try:
        turn = store.set_active_version(conversation_id, turn_id, body.index)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if turn is None:  # pragma: no cover — existence checked above
        raise HTTPException(status_code=404, detail="Turn not found")
    return turn


@router.post("/conversations/{conversation_id}/turns/{turn_id}/items/{item_id}/audio")
async def synthesize_item_audio(conversation_id: str, turn_id: str, item_id: str):
    """Synthesize (or return the already-synthesized) audio for one model item.

    Drives the client's per-message voice playback: the chat view calls this as
    it reveals each bubble, so synthesis overlaps playback instead of blocking the
    whole turn. Idempotent. Returns ``{"audio": {path, duration_ms,
    voice_preset_id} | null}`` — null when the item isn't spoken (voice off, wrong
    type, no preset, synth failure), which the client degrades to text.
    """
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    transcript = store.get_transcript(conversation_id) or {}
    turn = next((t for t in transcript.get("turns", []) if t.get("id") == turn_id), None)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    item = next((it for it in (turn.get("items") or []) if it.get("id") == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if turn.get("author") != "model":
        return {"audio": None}  # user-authored text is never synthesized
    character = get_character(conversation["counterpart_character_id"])
    if character is None:
        return {"audio": None}
    audio = await voice.synthesize_item(conversation, character, item)
    if audio:
        store.apply_audio(conversation_id, turn_id, {item_id: audio})
    return {"audio": audio}


# --- plugins ---------------------------------------------------------------

@router.get("/plugins")
def list_plugins():
    """List every registered plugin's manifest (the JSON-safe subset). The
    frontend loader uses this to inject enabled plugins' assets and to render the
    config dialog's Plugins toggle list."""
    return {"plugins": [p.manifest() for p in plugin_registry.list_plugins()]}


@router.post("/conversations/{conversation_id}/plugins/{plugin_id}/actions/{action}")
async def dispatch_plugin_action(
    conversation_id: str, plugin_id: str, action: str, params: dict = Body(default_factory=dict)
):
    """Run a plugin action and return its result dict.

    404 when the conversation, plugin, or action is missing; 409 when the plugin
    is not enabled for this conversation; otherwise the action's own errors map to
    4xx/5xx (a :class:`ValueError` from validation → 422). The action does its own
    work and returns whatever the frontend renders.
    """
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    plugin = plugin_registry.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    run = plugin.get_action(action)
    if run is None:
        raise HTTPException(status_code=404, detail="Action not found")
    enabled = plugin_registry.effective_enabled_ids(conversation.get("config") or {})
    if plugin_id not in enabled:
        raise HTTPException(status_code=409, detail="Plugin not enabled for this conversation")
    try:
        return await run(conversation_id, params or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --- transcript editing (edit / hide / delete) -----------------------------

def _require_item(conversation_id: str, turn_id: str, item_id: str) -> None:
    """404 if the conversation, turn, or item is missing."""
    transcript = store.get_transcript(conversation_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turn = next((t for t in transcript.get("turns", []) if t.get("id") == turn_id), None)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    if not any(it.get("id") == item_id for it in (turn.get("items") or [])):
        raise HTTPException(status_code=404, detail="Item not found")


@router.patch("/conversations/{conversation_id}/turns/{turn_id}/items/{item_id}")
def edit_item(conversation_id: str, turn_id: str, item_id: str, body: ItemPatch):
    """Edit one item in place: set its ``text`` and/or its ``hidden_from_context``
    flag. Editing does **not** re-run the model. Returns the updated turn."""
    _require_item(conversation_id, turn_id, item_id)
    turn: Optional[dict] = None
    if body.text is not None:
        turn = store.edit_item(conversation_id, turn_id, item_id, body.text)
    if body.hidden_from_context is not None:
        turn = store.set_item_hidden(conversation_id, turn_id, item_id, body.hidden_from_context)
    if turn is None:  # nothing set → return the current turn unchanged
        transcript = store.get_transcript(conversation_id) or {}
        turn = next((t for t in transcript.get("turns", []) if t.get("id") == turn_id), None)
    return turn


@router.delete("/conversations/{conversation_id}/turns/{turn_id}/items/{item_id}")
def delete_item(conversation_id: str, turn_id: str, item_id: str):
    """Delete one item. If it was the turn's last item, the turn is removed too —
    the response then is ``{"turn_deleted": turn_id}``; otherwise the updated turn."""
    _require_item(conversation_id, turn_id, item_id)
    return store.delete_item(conversation_id, turn_id, item_id)


@router.delete("/conversations/{conversation_id}/turns/{turn_id}", status_code=204)
def delete_turn(conversation_id: str, turn_id: str):
    """Delete a whole turn. Surviving turns keep their ids (no renumbering)."""
    if not store.delete_turn(conversation_id, turn_id):
        raise HTTPException(status_code=404, detail="Conversation or turn not found")
    return Response(status_code=204)


# --- per-turn trace read (dev tools) ---------------------------------------

@router.get("/conversations/{conversation_id}/turns/{turn_id}/trace")
def get_trace(conversation_id: str, turn_id: str):
    """Return the per-model-turn debug trace (``traces/<turn_id>.json``). 404 when
    the conversation or that turn's trace is absent."""
    if store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    trace = store.get_trace(conversation_id, turn_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str):
    """Export a whole conversation as one self-contained JSON bundle for bug
    reports: the conversation + full transcript + every per-turn trace, enriched
    with the pipeline version, the active prompts that produced the replies, and
    the counterpart character sheet (so the report reproduces the inputs). 404 when
    the conversation is absent. Read-only.

    Returned as a file attachment so hitting the URL in a browser downloads it; the
    UI fetches the JSON and saves it with the same name."""
    bundle = store.export_conversation(conversation_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    char_id = (bundle["conversation"] or {}).get("counterpart_character_id")
    try:
        character = get_character(char_id) if char_id else None
    except Exception:  # noqa: BLE001 — a missing/broken character must not block export
        character = None
    bundle["app"] = "prattletale"
    bundle["prompt_version"] = PRATTLETALE_PROMPT_VERSION
    bundle["exported_at"] = now_iso()
    bundle["active_prompts"] = _active_prompt_map()
    bundle["character"] = character
    filename = f"prattletale-{conversation_id}.json"
    return Response(
        content=json.dumps(bundle, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- prompt debug surface ---------------------------------------------------

# The Prattletale prompts that drive the live pipeline (UI-editable / resettable).
_DEBUG_PROMPT_KEYS = ("turn", "turn_system", "director", "repair")
# Retired keys shown for awareness; they no longer affect a reply.
_DEBUG_RETIRED_KEYS = ("variety", "feel_director", "turn.guard")


def _active_prompt_map() -> dict[str, dict]:
    """For each live Prattletale prompt, the entry actually in effect: its Prompt
    Pal id, whether a stored copy is shadowing the in-code default, and the resolved
    text. Shared by ``/debug/prompts`` and the conversation export so a bug report
    records exactly which prompts produced the replies."""
    out: dict[str, dict] = {}
    for key in _DEBUG_PROMPT_KEYS:
        try:
            active = pp_service.get_text("prattletale", key)
        except Exception:  # noqa: BLE001 — an unresolved/empty prompt is shown blank
            active = ""
        out[key] = {
            "id": pp_service.id_for("prattletale", key),
            "is_stored": pp_store.get_by_app_key("prattletale", key) is not None,
            "active_prompt": active,
        }
    return out


@router.get("/debug/prompts")
def debug_prompts():
    """Show which Prattletale Prompt Pal entry is actually active (stored copy vs
    in-code default) for each live prompt, plus the pipeline version — so it is
    never ambiguous which prompt produced a reply. Read-only."""
    return {
        "prompt_version": PRATTLETALE_PROMPT_VERSION,
        "prompts": _active_prompt_map(),
        "retired": list(_DEBUG_RETIRED_KEYS),
    }


@router.post("/debug/prompts/{key}/reset")
def reset_prompt(key: str):
    """Reset one Prattletale prompt to its in-code default by deleting the stored
    copy (so ``get_text`` falls back to the registered default). 404 for an unknown
    key; ``reset=false`` when there was no stored copy to remove."""
    if key not in _DEBUG_PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    entry = pp_store.get_by_app_key("prattletale", key)
    if entry is None:
        return {"reset": False, "key": key}
    pp_store.delete_entry(entry["id"])
    return {"reset": True, "key": key}
