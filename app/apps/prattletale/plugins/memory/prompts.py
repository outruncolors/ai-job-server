"""Editable Prompt Pal entries for the Remember plugin's **Gist** write path.

Registered at import time (like every app's ``prompts`` module). The plugin's
``seed_prompts`` writes any missing ``(prattletale, memory.gist)`` to the store so
it's tunable in the Prompt Pal UI; until then the in-code default here serves as
``service.get_text``'s fallback.

- ``memory.gist`` — distill a highlighted message (plus a little surrounding
  context) into one or two durable, self-contained facts worth remembering about
  the counterpart or the user. ``{{var.message}}`` is the highlighted line;
  ``{{var.context}}`` is the recent transcript around it.
- Its **guard** restates the same one-or-two-plain-sentences shape and repairs
  output that drifts (chat formatting, emoji, first-person address, preamble).
  Per the project guard rule, the prompt and guard are authored together: a change
  to one almost always needs the matching change to the other.
"""

from __future__ import annotations

from .....prompt_pal.registry import register

__all__ = ["GIST", "GIST_GUARD"]


GIST = (
    "You distill a moment from an ongoing text-message roleplay into durable "
    "long-term memory — a fact worth remembering for future conversations.\n\n"
    "Read the highlighted message (with the surrounding context for grounding) and "
    "write ONE or TWO short, self-contained, third-person factual statements that "
    "capture what is worth remembering — a preference, a detail about someone, a "
    "decision, a relationship fact, something that happened. Each statement must "
    "stand on its own without the surrounding chat (name who it is about; don't "
    "write \"he\"/\"she\"/\"they\" with no referent). Do NOT invent anything that "
    "is not supported by the text.\n\n"
    "<context>\n{{var.context}}\n</context>\n\n"
    "HIGHLIGHTED MESSAGE (what to remember):\n<message>\n{{var.message}}\n</message>\n\n"
    "Output only the factual statement(s) as plain prose — no preamble, no tags, "
    "no markdown, no quotation marks, no emoji, and do not address anyone in the "
    "second person."
)

GIST_GUARD = (
    "The following is a candidate long-term-memory note distilled from a "
    "conversation:\n<note>\n{{previous}}\n</note>\n\n"
    "Clean it into a durable memory note. Keep the meaning and the facts; do not "
    "invent anything.\n"
    "- Keep it to one or two short, self-contained third-person statements. If it "
    "addresses someone as \"you\", rewrite to name who it is about.\n"
    "- DELETE every emoji and emoticon.\n"
    "- Remove markdown, asterisks, code fences, quotation marks wrapping the whole "
    "note, tags, preamble, and any meta-commentary (\"Here's\", \"As an AI\", and "
    "the like).\n\n"
    "Output only the cleaned note — nothing else."
)


register(
    "prattletale", "memory.gist",
    title="Memory — gist (distill a fact)",
    prompt=GIST,
    tags=("memory", "plugin"),
    description="Distill a highlighted message into a durable long-term memory note.",
    guard={"enabled": True, "prompt": GIST_GUARD, "variables": {}},
)
