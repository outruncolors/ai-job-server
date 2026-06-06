"""Default content Prattletale seeds at startup (seed-if-absent).

The **message-shape** distribution lives in a *wildcard* rather than hard-coded in
the turn prompt so it is tunable in the Wildcards UI without a code change: the
turn prompt embeds ``%%Prattletale Message Style%%`` and the generator resolves a
weighted pick per turn. We seed a sensible default if the user has no wildcard by
that name yet, and never clobber one they've edited (mirrors Prompt Pal seeding).

Default distribution (weights are relative; these sum to 100 for readability):

- 40% a single spoken message,
- 30% one action + one message,
- 20% a small mix that includes narration / a feeling beat,
- 10% a short burst of two or more messages (more is rarer).
"""

from __future__ import annotations

from ... import wildcards as _wildcards

MESSAGE_STYLE_WILDCARD_NAME = "Prattletale Message Style"

# text = a natural-language directive the turn prompt embeds; weight = relative
# frequency. Phrased in the canonical message vocabulary (spoken dialogue /
# action / narration) so the model can follow it directly.
MESSAGE_STYLE_ENTRIES: list[dict] = [
    {
        "weight": 40,
        "text": (
            "Just one message this reply: a single spoken line and nothing else. "
            "No action, no narration — only the spoken text."
        ),
    },
    {
        "weight": 30,
        "text": (
            "One action and one message: a brief action beat (something physical "
            "you're doing) and a single spoken line. Nothing else."
        ),
    },
    {
        "weight": 20,
        "text": (
            "A small mix this reply: a spoken line together with an action and/or "
            "a short scene-or-feeling narration beat. Keep it to about two or "
            "three lines total."
        ),
    },
    {
        "weight": 10,
        "text": (
            "A quick burst this reply: two or more short spoken messages "
            "back-to-back, the way someone fires off rapid texts. Three is rarer, "
            "more than that rarer still. An action or narration line is optional."
        ),
    },
]


# ---- per-turn Dialogue Feel rolls ------------------------------------------
# Three independently-tunable wildcards that vary a reply's *micro-style* without
# touching the character's identity: a conversational move, an emotional shade,
# and a cadence. The generator resolves one weighted pick from each per turn (a
# fresh draw, like the message-style wildcard) into the turn prompt's
# {{var.dialogue_feel_roll}} block. A character can override any of these with a
# colon-suffixed wildcard ("<name>:<character_id>") so its rolls don't drift to
# the same generic style as everyone else; the generic wildcards below are the
# fallback. Seed-if-absent, never clobbering user edits.

DIALOGUE_MOVE_WILDCARD_NAME = "Prattletale Dialogue Move"
DIALOGUE_MOVE_ENTRIES: list[dict] = [
    {"weight": 30, "text": "Answer with a deflection first, then reveal one useful thing."},
    {"weight": 25, "text": "Ask one pointed question instead of explaining."},
    {"weight": 20, "text": "Push back on the other person's premise before giving ground."},
    {"weight": 15, "text": "Admit something indirectly — through a joke, an action, or an omission."},
    {"weight": 10, "text": "Change the subject toward something this character actually wants."},
]

EMOTIONAL_SHADE_WILDCARD_NAME = "Prattletale Emotional Shade"
EMOTIONAL_SHADE_ENTRIES: list[dict] = [
    {"weight": 35, "text": "guarded but curious"},
    {"weight": 25, "text": "irritated, but not done talking"},
    {"weight": 20, "text": "softness leaking through restraint"},
    {"weight": 10, "text": "cold, tactical focus"},
    {"weight": 10, "text": "playful, but using humor as armor"},
]

CADENCE_WILDCARD_NAME = "Prattletale Cadence"
CADENCE_ENTRIES: list[dict] = [
    {"weight": 30, "text": "one short sentence, then one sharper follow-up"},
    {"weight": 25, "text": "clipped fragments, like someone typing while distracted"},
    {"weight": 20, "text": "starts and stops, with a self-correction"},
    {"weight": 15, "text": "slow, deliberate pressure"},
    {"weight": 10, "text": "one unusually plain sentence with no flourish"},
]

# (wildcard name, entries, description) for the three feel-roll wildcards.
_DIALOGUE_FEEL_WILDCARDS: list[tuple[str, list[dict], str]] = [
    (DIALOGUE_MOVE_WILDCARD_NAME, DIALOGUE_MOVE_ENTRIES,
     "Prattletale per-turn conversational move (Dialogue Feel roll)."),
    (EMOTIONAL_SHADE_WILDCARD_NAME, EMOTIONAL_SHADE_ENTRIES,
     "Prattletale per-turn emotional shade (Dialogue Feel roll)."),
    (CADENCE_WILDCARD_NAME, CADENCE_ENTRIES,
     "Prattletale per-turn cadence (Dialogue Feel roll)."),
]


def _seed_wildcard_if_absent(name: str, entries: list[dict], description: str) -> bool:
    """Create one wildcard if no wildcard by that name exists (case-insensitive).
    Returns True when created, False when one already exists (left untouched)."""
    existing = any(
        (w.get("name") or "").lower() == name.lower()
        for w in _wildcards.list_wildcards()
    )
    if existing:
        return False
    _wildcards.create_wildcard(name, entries, description=description)
    return True


def seed_message_style_wildcard() -> bool:
    """Create the message-style wildcard if no wildcard by that name exists.

    Returns True if it was created, False if one already exists (left untouched).
    Best-effort; the caller swallows exceptions so seeding can't block startup.
    """
    return _seed_wildcard_if_absent(
        MESSAGE_STYLE_WILDCARD_NAME,
        MESSAGE_STYLE_ENTRIES,
        "How a Prattletale reply is shaped (single message / action+message / mix / burst).",
    )


def seed_dialogue_feel_wildcards() -> int:
    """Seed the three per-turn Dialogue Feel roll wildcards (seed-if-absent each).

    Returns the count created. Best-effort; the caller swallows exceptions so
    seeding can't block startup."""
    return sum(
        _seed_wildcard_if_absent(name, entries, description)
        for name, entries, description in _DIALOGUE_FEEL_WILDCARDS
    )
