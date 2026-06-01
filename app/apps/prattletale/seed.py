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


def seed_message_style_wildcard() -> bool:
    """Create the message-style wildcard if no wildcard by that name exists.

    Returns True if it was created, False if one already exists (left untouched).
    Best-effort; the caller swallows exceptions so seeding can't block startup.
    """
    existing = any(
        (w.get("name") or "").lower() == MESSAGE_STYLE_WILDCARD_NAME.lower()
        for w in _wildcards.list_wildcards()
    )
    if existing:
        return False
    _wildcards.create_wildcard(
        MESSAGE_STYLE_WILDCARD_NAME,
        MESSAGE_STYLE_ENTRIES,
        description="How a Prattletale reply is shaped (single message / action+message / mix / burst).",
    )
    return True
