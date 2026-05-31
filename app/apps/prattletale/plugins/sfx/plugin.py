"""The SFX plugin registration + its resolve/reroll/clear actions.

The platform owns SFX selection (:func:`app.sfx.resolver.resolve_sfx`); this
plugin only wires Prattletale state into it: it reads the conversation's SFX
config and the counterpart character's emote identity, resolves eligible items,
persists the descriptor via :func:`store.apply_sfx`, and records a per-item trace
section. ``resolve-turn`` fans the same item resolver across a turn.
"""

from __future__ import annotations

from app.apps.hoodat.characters_store import get_character
from app.apps.prattletale import store
from app.sfx import resolver

from ..base import Plugin
from ..registry import register

_FRONTEND = [
    "apps/prattletale/plugins/sfx/sfx.js",
    "apps/prattletale/plugins/sfx/sfx.css",
]

_FINAL_STATES = {"skipped", "none", "rejected", "resolved", "error"}


def _character_inputs(conversation: dict) -> tuple[str | None, str]:
    """(emote identity, character label) from the counterpart character. The
    identity is None when the character has no enabled SFX binding."""
    character = get_character(conversation.get("counterpart_character_id"))
    if character is None:
        return None, ""
    sfx_cfg = (character.get("speaking_style") or {}).get("sfx") or {}
    identity = sfx_cfg.get("emotes_identity") if sfx_cfg.get("enabled") else None
    label = character.get("name") or ""
    return identity, label


async def _resolve_one(conversation: dict, transcript: dict, turn_id: str, item_id: str,
                       *, force: bool) -> dict | None:
    """Resolve SFX for one item and persist it. Returns the descriptor, or None
    when the item can't be found."""
    turn = next((t for t in transcript.get("turns", []) if t.get("id") == turn_id), None)
    if turn is None:
        return None
    item = next((it for it in turn.get("items", []) if it.get("id") == item_id), None)
    if item is None:
        return None

    config = conversation.get("config") or {}
    # Honour final states on reload (don't re-roll) unless an explicit reroll.
    existing = item.get("sfx")
    if not force and existing and existing.get("status") in _FINAL_STATES:
        return existing

    if not config.get("sfx_enabled"):
        desc = {"schema_version": resolver.SFX_SCHEMA_VERSION, "status": "skipped",
                "reason": "disabled", "created_at": resolver._now()}
        store.apply_sfx(conversation["id"], turn_id, {item_id: desc})
        return desc

    identity, label = _character_inputs(conversation)
    desc, trace = await resolver.resolve_sfx(
        item_type=item.get("type"),
        item_text=item.get("text") or "",
        author=item.get("author") or "model",
        identity=identity,
        domains=config.get("sfx_domains") or [],
        character_label=label,
        chance=float(config.get("sfx_chance", 0.65)),
        force=force,
    )
    store.apply_sfx(conversation["id"], turn_id, {item_id: desc})
    _append_trace(conversation["id"], turn_id, item_id, trace)
    return desc


def _append_trace(conversation_id: str, turn_id: str, item_id: str, trace: dict) -> None:
    existing = store.get_trace(conversation_id, turn_id) or {}
    existing.setdefault("sfx", {}).setdefault("items", {})[item_id] = trace
    store.write_trace(conversation_id, turn_id, existing)


async def run_resolve_item(conversation_id: str, params: dict) -> dict:
    """Resolve SFX for a single item. params: {turn_id, item_id, force?}."""
    turn_id = params.get("turn_id")
    item_id = params.get("item_id")
    if not turn_id or not item_id:
        raise ValueError("turn_id and item_id are required")
    conversation = store.get_conversation(conversation_id)
    transcript = store.get_transcript(conversation_id)
    if conversation is None or transcript is None:
        raise ValueError(f"conversation not found: {conversation_id}")
    desc = await _resolve_one(conversation, transcript, turn_id, item_id,
                              force=bool(params.get("force")))
    if desc is None:
        raise ValueError("item not found")
    return {"turn_id": turn_id, "item_id": item_id, "sfx": desc}


async def run_resolve_turn(conversation_id: str, params: dict) -> dict:
    """Resolve SFX for every eligible item in a turn. params: {turn_id, force?}."""
    turn_id = params.get("turn_id")
    if not turn_id:
        raise ValueError("turn_id is required")
    conversation = store.get_conversation(conversation_id)
    transcript = store.get_transcript(conversation_id)
    if conversation is None or transcript is None:
        raise ValueError(f"conversation not found: {conversation_id}")
    turn = next((t for t in transcript.get("turns", []) if t.get("id") == turn_id), None)
    if turn is None:
        raise ValueError("turn not found")
    force = bool(params.get("force"))
    results = []
    for item in turn.get("items", []):
        if item.get("type") not in resolver.ELIGIBLE_TYPES:
            continue
        desc = await _resolve_one(conversation, transcript, turn_id, item.get("id"), force=force)
        if desc is not None:
            results.append({"item_id": item.get("id"), "sfx": desc})
    return {"turn_id": turn_id, "items": results}


async def run_reroll_item(conversation_id: str, params: dict) -> dict:
    """Re-resolve one item, skipping the chance roll and any prior final state."""
    return await run_resolve_item(conversation_id, {**params, "force": True})


async def run_clear_item(conversation_id: str, params: dict) -> dict:
    """Remove the SFX descriptor from one item. params: {turn_id, item_id}."""
    turn_id = params.get("turn_id")
    item_id = params.get("item_id")
    if not turn_id or not item_id:
        raise ValueError("turn_id and item_id are required")
    if store.apply_sfx(conversation_id, turn_id, {item_id: None}) is None:
        raise ValueError("conversation or turn not found")
    return {"turn_id": turn_id, "item_id": item_id, "sfx": None}


def _seed_prompts() -> None:
    """Seed the SFX Prompt Pal entries (registered on import of app.sfx.prompts)."""
    import app.sfx.prompts  # noqa: F401 — ensures register() ran
    from app.prompt_pal.registry import seed_registered

    seed_registered()


plugin = Plugin(
    id="sfx",
    name="Sound Effects",
    description="Adds optional emote sound effects after action and narration items.",
    frontend=_FRONTEND,
    actions={
        "resolve-item": run_resolve_item,
        "resolve-turn": run_resolve_turn,
        "reroll-item": run_reroll_item,
        "clear-item": run_clear_item,
    },
    default_enabled=True,
    seed_prompts=_seed_prompts,
)

register(plugin)
