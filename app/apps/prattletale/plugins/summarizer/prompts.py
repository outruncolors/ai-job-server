"""Editable Prompt Pal entries for the Summarizer engine.

Registered at import time (like every app's ``prompts`` module). The plugin's
``seed_prompts`` writes any missing ``(prattletale, summarize.*)`` to the store so
they're tunable in the Prompt Pal UI; until then the in-code defaults here serve
as ``service.get_text``'s fallback.

- ``summarize.map`` — condense one chunk of the conversation. ``{{var.detail}}``
  (the chosen level directive) leads; ``{{var.transcript}}`` is the chunk;
  ``{{var.focus}}`` (optional emphasis) is appended at the end.
- ``summarize.reduce`` — merge several partial summaries into one. Same
  ``{{var.detail}}`` / ``{{var.focus}}``; ``{{var.partials}}`` is the joined list.
- ``summarize.level.{brief,standard,detailed}`` — the three detail directives,
  composed into ``{{var.detail}}`` by the engine.
"""

from __future__ import annotations

from .....prompt_pal.registry import register

__all__ = ["MAP", "REDUCE", "LEVEL_BRIEF", "LEVEL_STANDARD", "LEVEL_DETAILED"]


MAP = (
    "You are condensing one section of an ongoing text-message roleplay "
    "conversation so its content can be carried forward as compact context.\n\n"
    "{{var.detail}}\n\n"
    "Summarize the conversation section below as a neutral third-person recap: "
    "what happened, what was said and decided, how the characters felt, and any "
    "facts or details established. Preserve names and concrete specifics. Do NOT "
    "invent anything that is not present, and do not add commentary.\n\n"
    "<conversation>\n{{var.transcript}}\n</conversation>\n\n"
    "{{var.focus}}\n\n"
    "Output only the summary prose — no preamble, no tags, no markdown, no emoji."
)

REDUCE = (
    "You are merging several partial summaries of consecutive sections of one "
    "ongoing text-message roleplay conversation into a single coherent summary.\n\n"
    "{{var.detail}}\n\n"
    "Combine the partial summaries below into one neutral third-person recap that "
    "reads as a single continuous account, in chronological order. Keep names and "
    "concrete specifics; do not repeat the same beat twice; do not invent anything "
    "not present in the partials.\n\n"
    "<partials>\n{{var.partials}}\n</partials>\n\n"
    "{{var.focus}}\n\n"
    "Output only the merged summary prose — no preamble, no tags, no markdown, no "
    "emoji."
)

LEVEL_BRIEF = (
    "Keep it very brief: two or three sentences capturing only the most important "
    "beats and the current state of things."
)

LEVEL_STANDARD = (
    "Aim for a balanced summary: a short paragraph covering the key events, "
    "decisions, and feelings — enough to continue the conversation without the "
    "originals."
)

LEVEL_DETAILED = (
    "Be thorough: capture the events, the notable dialogue beats, decisions, and "
    "emotional shifts in detail and in order — while staying clearly more compact "
    "than the original conversation."
)


register(
    "prattletale", "summarize.map",
    title="Summarize — map (per chunk)",
    prompt=MAP,
    tags=("summarizer", "plugin"),
    description="Condense one chunk of the conversation into a partial summary.",
)
register(
    "prattletale", "summarize.reduce",
    title="Summarize — reduce (merge partials)",
    prompt=REDUCE,
    tags=("summarizer", "plugin"),
    description="Merge several partial summaries into one.",
)
register(
    "prattletale", "summarize.level.brief",
    title="Summarize — detail: Brief",
    prompt=LEVEL_BRIEF,
    tags=("summarizer", "plugin"),
    description="The 'Brief' detail directive (composed into {{var.detail}}).",
)
register(
    "prattletale", "summarize.level.standard",
    title="Summarize — detail: Standard",
    prompt=LEVEL_STANDARD,
    tags=("summarizer", "plugin"),
    description="The 'Standard' detail directive (composed into {{var.detail}}).",
)
register(
    "prattletale", "summarize.level.detailed",
    title="Summarize — detail: Detailed",
    prompt=LEVEL_DETAILED,
    tags=("summarizer", "plugin"),
    description="The 'Detailed' detail directive (composed into {{var.detail}}).",
)
