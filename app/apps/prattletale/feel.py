"""Dialogue Feel System — pure render/merge helpers for the turn prompt.

Three layered levers give a Prattletale reply a recognizable, per-character
*conversational fingerprint* without replacing the ``turn → variety → guard``
pipeline:

- :func:`render_voice_feel` — the **stable** profile: a Hoodat character's
  ``speaking_style.voice_feel`` (cadence / lexicon / tactic / subtext / avoid),
  with a per-conversation ``config.dialogue_feel`` override layered on top
  (non-empty override field wins, else the character default).
- :func:`render_voice_examples` — 3–6 concrete tagged example lines for the model
  to imitate (conversation override examples, else the character's).
- :func:`resolve_dialogue_feel_roll` — a **per-turn** weighted micro-style roll
  (Move / Emotional Shade / Cadence), drawn fresh each turn from the seeded
  wildcards, with an optional per-character override convention
  (``"<base name>:<character_id>"``).

Each helper returns a **self-contained block string** (its own header + tagged
section) or ``""`` — never a bare value. This is deliberate: ``compose()`` leaves
an unresolved ``{{var.NAME}}`` token *literal* (it does not render empty), so the
turn prompt drops in ``{{var.voice_feel}}`` etc. and an empty section simply
vanishes instead of leaving a dangling header. The first two are **pure** (store
reads only) and computed in :func:`generator.build_context`; the roll uses the
wildcard RNG and is computed per turn in :func:`generator.build_turn_request`.
"""

from __future__ import annotations

from ...wildcards import list_wildcards, resolve_wildcards
from .seed import (
    CADENCE_WILDCARD_NAME,
    DIALOGUE_MOVE_WILDCARD_NAME,
    EMOTIONAL_SHADE_WILDCARD_NAME,
)

# Cap so the examples block never bloats the prompt.
_MAX_VOICE_EXAMPLES = 6

# (voice_feel field, prompt label) in render order. Drives both the merge and the
# rendered block; ``enabled`` lives on the model, not here.
_FEEL_FIELDS: list[tuple[str, str]] = [
    ("cadence", "Cadence"),
    ("lexicon", "Lexicon"),
    ("conversational_tactic", "Conversational tactic"),
    ("subtext_rules", "Subtext"),
    ("avoid", "Avoid"),
]

# (rendered label, base wildcard name) for the per-turn roll, in render order.
_FEEL_ROLL_CATEGORIES: list[tuple[str, str]] = [
    ("Emotional shade", EMOTIONAL_SHADE_WILDCARD_NAME),
    ("Move", DIALOGUE_MOVE_WILDCARD_NAME),
    ("Cadence", CADENCE_WILDCARD_NAME),
]


# ---- stable voice-feel profile ---------------------------------------------

def _character_voice_feel(character: dict) -> dict:
    """The character's ``speaking_style.voice_feel`` block (``{}`` if absent)."""
    return ((character.get("speaking_style") or {}).get("voice_feel")) or {}


def _merge_feel_fields(character: dict, conversation: dict) -> dict[str, str]:
    """Merge character default + conversation override into ``{field: value}`` for
    the non-empty fields only. Gated by ``config.dialogue_feel_enabled`` (master,
    default on); the character's ``voice_feel.enabled`` flag (default off) gates
    whether its *own* fields contribute — a conversation override applies either
    way."""
    config = conversation.get("config") or {}
    if not config.get("dialogue_feel_enabled", True):
        return {}
    base = _character_voice_feel(character)
    base_on = bool(base.get("enabled"))
    override = config.get("dialogue_feel") or {}
    merged: dict[str, str] = {}
    for field, _label in _FEEL_FIELDS:
        ov = str(override.get(field) or "").strip()
        bv = str(base.get(field) or "").strip() if base_on else ""
        value = ov or bv
        if value:
            merged[field] = value
    return merged


def render_voice_feel(character: dict, conversation: dict) -> str:
    """Render the stable VOICE FEEL PROFILE block, or ``""`` when nothing is set."""
    merged = _merge_feel_fields(character, conversation)
    if not merged:
        return ""
    body = "\n".join(f"{label}: {merged[field]}" for field, label in _FEEL_FIELDS if field in merged)
    return (
        "VOICE FEEL PROFILE — the character's conversational fingerprint; follow it:\n"
        f"<voice_feel>\n{body}\n</voice_feel>"
    )


def _example_lines(character: dict, conversation: dict) -> list[str]:
    """3–6 voice-example lines: conversation override if any are set, else the
    character's. Empty/whitespace lines dropped; capped. ``[]`` when disabled or
    none configured. (Character ``dialogue_examples`` are intentionally **not**
    pulled in — they already render inside ``{{var.character}}``.)"""
    config = conversation.get("config") or {}
    if not config.get("dialogue_feel_enabled", True):
        return []
    override = (config.get("dialogue_feel") or {}).get("examples") or []
    if any(str(e).strip() for e in override):
        source = override
    else:
        base = _character_voice_feel(character)
        if not base.get("enabled"):
            return []
        source = base.get("examples") or []
    lines = [str(e).strip() for e in source if str(e).strip()]
    return lines[:_MAX_VOICE_EXAMPLES]


def render_voice_examples(character: dict, conversation: dict) -> str:
    """Render the RECENT GOOD VOICE EXAMPLES block, or ``""`` when there are none."""
    lines = _example_lines(character, conversation)
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "RECENT GOOD VOICE EXAMPLES — imitate the cadence, pressure, and tactics, "
        "not the exact words:\n"
        f"<voice_examples>\n{body}\n</voice_examples>"
    )


# ---- per-turn feel roll -----------------------------------------------------

def _resolve_category(base_name: str, character_id: str, existing_lower: set[str]) -> str:
    """Resolve one feel-roll category to a weighted pick. Prefer the
    character-specific wildcard ``"<base>:<character_id>"`` when it exists and has
    entries, else the generic ``base_name``. ``""`` when neither yields a pick (a
    present-but-empty wildcard falls through to the next candidate)."""
    candidates = []
    if character_id:
        candidates.append(f"{base_name}:{character_id}")
    candidates.append(base_name)
    for name in candidates:
        if name.lower() not in existing_lower:
            continue
        # resolve_wildcards returns the literal %%token%% when the wildcard has no
        # entries; "%%" in the result means "no real pick" -> try the next one.
        picked = resolve_wildcards(f"%%{name}%%").strip()
        if picked and "%%" not in picked:
            return picked
    return ""


def resolve_dialogue_feel_roll(character_id: str, *, enabled: bool = True) -> str:
    """Render THIS TURN'S DIALOGUE FEEL block from a fresh weighted draw of the
    Move / Emotional Shade / Cadence wildcards (per-character override honored).
    ``""`` when ``enabled`` is False or nothing resolved (e.g. wildcards absent)."""
    if not enabled:
        return ""
    existing_lower = {(w.get("name") or "").lower() for w in list_wildcards()}
    lines: list[str] = []
    for label, base_name in _FEEL_ROLL_CATEGORIES:
        value = _resolve_category(base_name, character_id, existing_lower)
        if value:
            lines.append(f"{label}: {value}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "THIS TURN'S DIALOGUE FEEL — obey without mentioning it:\n"
        f"<dialogue_feel_roll>\n{body}\n</dialogue_feel_roll>"
    )
