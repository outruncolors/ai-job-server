"""Prompt Pal entries for SFX resolution: an emote chooser + a skeptical guard.

Registered under app ``"sfx"`` so they appear in the Prompt Pal editor and can be
edited live (store copy wins). The resolver (app/sfx/resolver.py) supplies the
``{{var.*}}`` values and runs the guard as a second LLM step over ``{{previous}}``.
"""

from __future__ import annotations

from app.prompt_pal.registry import register

CHOOSE_EMOTE = (
    "You attach at most ONE sound effect to a single line of an interactive story.\n\n"
    "Line type: {{var.item_type}}\n"
    "Author: {{var.author}}\n"
    "Line text:\n<line>\n{{var.item_text}}\n</line>\n\n"
    "Character: {{var.character}}\n\n"
    "Available sound categories (a compact catalog — count, sample descriptions, tags):\n"
    "<catalog>\n{{var.catalog}}\n</catalog>\n\n"
    "Rules:\n"
    "- Choose at most one category that a listener would clearly hear in this line.\n"
    "- Prefer an EXPLICIT sound (a sneeze, a laugh, a sigh, a cough) over an implied mood.\n"
    "- Never choose for spoken dialogue, and never invent a category that isn't listed.\n"
    "- If nothing in the catalog genuinely fits, return decision \"none\". Do not force a match.\n\n"
    "Respond with ONLY a JSON object, no preamble:\n"
    "{\"decision\": \"choose\"|\"none\", \"category\": <string|null>, "
    "\"effect_id\": <string|null>, \"confidence\": <0..1>, \"reason\": <short string>}"
)

GUARD_EMOTE = (
    "You are a skeptical reviewer deciding whether a chosen sound effect should play.\n\n"
    "The previous step produced this JSON selection:\n<selection>\n{{previous}}\n</selection>\n\n"
    "The line it applies to:\n"
    "Line type: {{var.item_type}}\n<line>\n{{var.item_text}}\n</line>\n\n"
    "Reject (and explain) when:\n"
    "- the match is contrived or only weakly related to what the line describes,\n"
    "- the line conveys a mood rather than an audible sound,\n"
    "- the cue would read as unintentionally comedic or distracting.\n"
    "Keep only when a listener would immediately understand why the sound played.\n"
    "If the selection's decision is already \"none\", keep it.\n\n"
    "Respond with ONLY a JSON object, no preamble:\n"
    "{\"decision\": \"keep\"|\"reject\", \"reason\": <short string>}"
)


def _guard() -> dict:
    return {"enabled": True, "prompt": GUARD_EMOTE, "variables": {}}


register(
    "sfx", "choose_emote",
    title="Choose emote SFX",
    prompt=CHOOSE_EMOTE,
    tags=("sfx", "choose"),
    description="Pick at most one sound-effect category for an action/narration line.",
    guard=_guard(),
)
