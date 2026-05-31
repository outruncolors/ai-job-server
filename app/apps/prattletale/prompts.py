"""Prattletale's turn-generation prompt + tagged-line parser.

Registered at import time with Prompt Pal:
- ``turn`` — the model's reply prompt. It instructs the model to answer as the
  counterpart in the cadence of a texting burst: an ordered stack of short,
  texty bubbles, **one tagged line per bubble**
  (``[say]``/``[do]``/``[narration]``/``[feel]``). It consumes
  ``{{var.character}}`` (the rendered Hoodat sheet), ``{{var.scenario}}``,
  ``{{var.role_instructions}}``, ``{{var.user_persona}}`` and
  ``{{var.transcript}}`` (filled at call time by the generator's
  ``build_context``). It carries a **guard** — a second editor LLM pass
  (Hoodat's ``SPOKEN_ONLY_GUARD`` is the precedent) that does **format hygiene
  only**: every line tagged, leaked meta / OOC stripped, no bubbles merged.

The tagged-line format (not JSON) is deliberate: a chat turn is an open-ended
ordered sequence of short strings, and the failure mode that matters is "model
wrapped dialogue in prose / added a preamble", which the format degrades on
gracefully (untagged line -> dialogue) instead of throwing.

``parse_items(raw)`` turns the (guarded) output into ordered ``{type, text}``
dicts; ``_strip_fences(raw)`` peels a ```` ``` ```` wrapper first. ``ItemType``
values come from :mod:`app.apps.prattletale.models`.
"""

from __future__ import annotations

import re

from ...prompt_pal.registry import register
from .generator import GenerationError  # canonical home; re-exported here for the parser
from .models import ItemType

__all__ = ["GenerationError", "TURN", "TURN_GUARD", "parse_items"]


# ---- turn prompt + format-hygiene guard ------------------------------------

TURN = (
    "You are playing a fictional character in an iMessage-style text roleplay. "
    "You ARE this character — reply only as them, never as an assistant.\n\n"
    "The character you are playing:\n<character>\n{{var.character}}\n</character>\n\n"
    "Scenario / setting:\n<scenario>\n{{var.scenario}}\n</scenario>\n\n"
    "Roleplay instructions:\n"
    "<role_instructions>\n{{var.role_instructions}}\n</role_instructions>\n\n"
    "Who you are texting with:\n<user_persona>\n{{var.user_persona}}\n</user_persona>\n\n"
    "The conversation so far (oldest first):\n"
    "<transcript>\n{{var.transcript}}\n</transcript>\n\n"
    "Reply as the character, in the cadence of a real texting burst: an ordered "
    "stack of short, texty bubbles. React to what the other person actually just "
    "said. Keep each bubble short and natural, the way someone really texts, and "
    "use several bubbles when it fits (a beat of action or narration, then what "
    "they say).\n\n"
    "Tag EVERY line with exactly one tag at its very start:\n"
    "- [say] — spoken words / what the character says or texts\n"
    "- [do] — a physical action the character takes\n"
    "- [narration] — third-person scene or event description\n"
    "- [feel] — narration of the character's inner / emotional state\n\n"
    "Rules:\n"
    "- One bubble per line. Never combine multiple bubbles onto one line.\n"
    "- Every line must start with one of the four tags above.\n"
    "- No preamble, no out-of-character notes, no markdown, no code fences.\n\n"
    "Example shape:\n"
    "[narration] She doesn't look up from the menu.\n"
    "[say] Where else would I be."
)

# A guard is a second "editor" LLM pass that runs over the first step's output
# (the chain token {{previous}}). This one does FORMAT HYGIENE ONLY — it must not
# rewrite content or merge bubbles, so the parser stays trivial.
TURN_GUARD = (
    "The following is a character's text-roleplay reply, written as a stack of "
    "tagged bubbles (one per line):\n<reply>\n{{previous}}\n</reply>\n\n"
    "Clean it up for FORMAT HYGIENE ONLY. Do NOT change the wording, meaning, "
    "voice, or the number of bubbles.\n"
    "- Ensure every non-empty line starts with exactly one tag: [say], [do], "
    "[narration], or [feel]. If a line has no tag, prepend the most fitting one "
    "(spoken words -> [say]).\n"
    "- Remove any leaked internal monologue, meta-commentary, or assistant "
    "boilerplate (\"As an AI\", \"Sure, here's\", \"Here's my response:\", and the "
    "like) and any out-of-character (OOC) notes.\n"
    "- Remove markdown, code fences, and any quotes wrapping the whole reply.\n"
    "- Do NOT merge multiple bubbles into one line, and do NOT split one bubble "
    "into several. Keep the bubbles and their order exactly as they are.\n\n"
    "Output only the cleaned tagged lines — nothing else."
)

register(
    "prattletale",
    "turn",
    title="Chat turn",
    prompt=TURN,
    tags=("turn", "chat"),
    variables={},
    description="Reply as the Hoodat counterpart as a stack of tagged texty bubbles.",
    guard={"enabled": True, "prompt": TURN_GUARD, "variables": {}},
)


# ---- tagged-line parser ----------------------------------------------------

# Maps the model-facing tag to the on-disk ItemType value.
_TAG_TO_TYPE = {
    "say": ItemType.dialogue.value,
    "do": ItemType.action.value,
    "narration": ItemType.narration.value,
    "feel": ItemType.narration_emotion.value,
}

_LINE_RE = re.compile(r"^\s*\[(\w+)\]\s*(.+)$")


def _strip_fences(raw: str) -> str:
    """Peel a single ```` ``` ```` code-fence wrapper (optionally language-hinted)."""
    text = (raw or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening fence line (``` or ```lang).
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    # Drop the closing fence line if present.
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_items(raw: str) -> list[dict]:
    """Parse tagged-line model output into ordered ``{type, text}`` item dicts.

    Each ``[tag] text`` line becomes one item (``say``->dialogue, ``do``->action,
    ``narration``->narration, ``feel``->narration_emotion). An untagged (or
    unknown-tag) non-empty line **coalesces into the previous item's text**; a
    lone leading untagged line defaults to ``dialogue``. Raises
    :class:`GenerationError` on empty / whitespace-only input.
    """
    items: list[dict] = []
    for line in _strip_fences(raw).splitlines():
        if not line.strip():
            continue
        m = _LINE_RE.match(line)
        item_type = _TAG_TO_TYPE.get(m.group(1).lower()) if m else None
        if item_type is not None:
            items.append({"type": item_type, "text": m.group(2).strip()})
        elif items:
            # Untagged / unrecognized-tag continuation -> append to the prior bubble.
            items[-1]["text"] = f"{items[-1]['text']} {line.strip()}".strip()
        else:
            # A lone leading untagged line is taken as spoken dialogue.
            items.append({"type": ItemType.dialogue.value, "text": line.strip()})
    if not items:
        raise GenerationError("model output produced no items")
    return items
