"""Pydantic schemas for Prattletale conversations and transcripts.

A **conversation** is a folder on disk: ``conversation.json`` (metadata,
scenario, role instructions, device-user, config) + ``transcript.json`` (ordered
turns -> items).

Two units structure the transcript:

- a **turn** is one side's atomic contribution — the unit of alternation,
  context-window slicing, and retry (``{id, author, created_at, job_id?,
  items}``);
- an **item** is one rendered bubble (``{id, turn_id, author, type, text,
  status, audio, hidden_from_context, created_at}``). The model legitimately
  emits several bubbles per reply (a narration beat, then dialogue), so items
  cannot collapse into one blob.

``audio`` is ``None`` in the text-first phase; the voice session (SP6) sets
``{"path": "media/<item>.wav", "duration_ms": N, "voice_preset_id": "..."}``.
The ``config`` voice flags ship **inert** so SP6 activates them with no schema
migration. ``hidden_from_context`` ships honored-but-always-false so the
Phase-2 message-editing feature needs no pipeline change.

These models describe the on-disk shapes; the store
(:mod:`app.apps.prattletale.store`) is the read/write boundary and assigns
server-controlled fields (``id`` slug, ids, timestamps).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ItemType(str, Enum):
    """The kind of bubble an item renders as."""

    dialogue = "dialogue"  # spoken words (the only TTS-eligible type in SP6)
    action = "action"  # a physical beat (e.g. slides over the sugar)
    narration = "narration"  # third-person scene/event text
    narration_emotion = "narration_emotion"  # narration of the counterpart's inner state
    system_error = "system_error"  # a failed model turn, never fed back into context
    summary = "summary"  # a plugin-posted recap of earlier turns (kept in context)
    command = "command"  # a user-issued out-of-character order the model must obey
    ooc = "ooc"  # an out-of-character side message (OOC plugin); excluded from IC context


class Author(str, Enum):
    """Which side authored a turn / item."""

    user = "user"
    model = "model"
    system = "system"  # app/plugin-authored (e.g. a Summarizer recap) — avatar-less


class ItemStatus(str, Enum):
    """Lifecycle of a single item."""

    committed = "committed"
    generating = "generating"
    error = "error"


class Item(BaseModel):
    """One rendered bubble within a turn."""

    id: str
    turn_id: str
    author: Author
    type: ItemType
    text: str
    status: ItemStatus = ItemStatus.committed
    audio: Optional[dict] = None
    # Compact SFX after-cue descriptor (see app/sfx/resolver.py). Additive like
    # ``audio``: absent until the SFX plugin resolves the item. status ∈
    # {skipped, none, rejected, resolved, error}; only "resolved" carries a clip.
    sfx: Optional[dict] = None
    hidden_from_context: bool = False
    created_at: str


class TurnVersion(BaseModel):
    """One regenerated alternative of a model turn — a snapshot of its items.

    Created lazily: a turn that has never been regenerated carries ``versions=None``
    (and its ``items`` are the only copy). On the first regenerate the current state
    is captured as version 0, the new draft as version 1, and ``Turn.items`` becomes
    a mirror of the active version (so every downstream reader is unchanged).
    """

    items: list[Item] = Field(default_factory=list)
    job_id: Optional[str] = None
    created_at: str


class Turn(BaseModel):
    """One side's atomic contribution — an ordered stack of items.

    ``versions``/``active_version`` back the regenerate feature: when ``versions``
    is non-None the turn has more than one generated alternative and ``items``
    mirrors ``versions[active_version].items``. ``versions=None`` (the default)
    means the turn was never regenerated — the common case for user turns and
    first-pass model turns.
    """

    id: str
    author: Author
    created_at: str
    job_id: Optional[str] = None
    items: list[Item] = Field(default_factory=list)
    versions: Optional[list[TurnVersion]] = None
    active_version: int = 0


class DeviceUser(BaseModel):
    """The human end of the conversation (the 'device owner')."""

    display_name: str = "You"
    persona: str = ""
    avatar_path: Optional[str] = None


class DialogueFeel(BaseModel):
    """Per-conversation **override** layer for the character's VoiceFeel fingerprint.

    Same fields as ``hoodat.models.VoiceFeel`` minus ``enabled`` (the conversation
    gate lives on ``ConversationConfig.dialogue_feel_enabled``). Every field is
    empty by default; a non-empty field overrides the character's value, an empty
    one falls through to the character default. ``examples`` (when non-empty)
    replaces the character's voice examples for this chat."""

    cadence: str = ""
    lexicon: str = ""
    conversational_tactic: str = ""
    subtext_rules: str = ""
    avoid: str = ""
    examples: list[str] = Field(default_factory=list)


class ConversationConfig(BaseModel):
    """Forward-compatibility block. Phase 1 reads only ``context_window_turns``.

    The voice flags ship **inert** so the voice session (SP6) activates them
    with no schema migration.
    """

    context_window_turns: int = 12
    voice_enabled: bool = False
    typing_timing_enabled: bool = False
    # RETIRED: the old middle "variety" LLM pass (anti-monotony rewrite). Its job
    # is now done up-front by the director plan, so this defaults OFF and the build
    # path skips the step regardless. Field kept so existing configs stay valid.
    variety_pass_enabled: bool = False
    # When on, the turn step sends the model a real sequenced role array
    # (system + user/assistant transcript turns) instead of one flattened user
    # prompt. Default on; the single-prompt path remains as the fallback.
    structured_chat_history: bool = True
    # The per-turn director: a small LLM pre-pass that returns a JSON plan (move,
    # stance, reply shape, what to reference/avoid) injected into generation, and
    # subsumes the old shade/move/cadence feel roll. Default on. Falls back to the
    # weighted wildcard feel roll when off or when the director call fails.
    director_enabled: bool = True
    # When on, a last-resort LLM "repair" pass runs ONLY if the deterministic
    # cleanup + parser still can't produce usable items. Default on.
    repair_enabled: bool = True
    # Dev visibility: when on, the per-turn trace carries extra payload (director
    # plan, pattern summary, structured messages, repair info) and the frontend
    # exposes the Prattletale prompt-debug surface.
    debug_prattletale: bool = False
    # Plugin ids enabled for this conversation. A plugin's composer mode/panel and
    # actions are only available when its id is listed here. New conversations
    # start with each plugin whose ``default_enabled`` is true (seeded by the
    # frontend on creation); the router gates action dispatch on membership.
    enabled_plugins: list[str] = Field(default_factory=list)
    # SFX plugin knobs. ``sfx_enabled`` gates emote after-cues; ``sfx_chance`` is
    # the per-eligible-item probability (rolled before any LLM call); ``sfx_domains``
    # lists the global SFX domains (e.g. ["lewd"]) live for this conversation — the
    # NSFW/extra-catalog gate. Character Emotes need no domain entry.
    sfx_enabled: bool = False
    sfx_chance: float = 0.65
    sfx_domains: list[str] = Field(default_factory=list)
    # Dialogue Feel System. ``dialogue_feel_enabled`` gates the stable VoiceFeel
    # profile block (character default + the ``dialogue_feel`` override below);
    # ``dialogue_feel_roll_enabled`` gates the per-turn weighted micro-style roll
    # (Move / Emotional Shade / Cadence wildcards). Both default on; the rendered
    # blocks simply collapse to empty when nothing is configured.
    dialogue_feel_enabled: bool = True
    dialogue_feel_roll_enabled: bool = True
    # DEPRECATED: superseded by ``director_enabled`` (the rich JSON director now
    # owns per-turn feel). Field kept so existing configs stay valid; no longer read.
    dialogue_feel_director_enabled: bool = False
    dialogue_feel: DialogueFeel = Field(default_factory=DialogueFeel)


class Conversation(BaseModel):
    """Conversation metadata (``conversation.json``)."""

    schema_version: int = 1
    type: str = "prattletale_conversation"
    id: str
    title: str
    counterpart_character_id: str
    device_user: DeviceUser = Field(default_factory=DeviceUser)
    scenario: str = ""
    role_instructions: str = ""
    config: ConversationConfig = Field(default_factory=ConversationConfig)
    created_at: str
    updated_at: str


class Transcript(BaseModel):
    """The ordered turn log (``transcript.json``)."""

    schema_version: int = 1
    conversation_id: str
    turns: list[Turn] = Field(default_factory=list)
    next_turn_seq: int = 1
