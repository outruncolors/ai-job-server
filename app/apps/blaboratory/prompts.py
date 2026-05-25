"""In-code prompt registry for Blaboratory resident generation.

Keyed by id so the set migrates cleanly to the composable prompt-JSON system
later (design.md Part 2 → Prompt system): a leaf prompt is just text with
`{{vars}}`, which is exactly what these strings are. The chain executor renders
`{{input}}` / `{{previous}}` via `app/chain/template.py`, so the ideate prompts
read user content from `{{input}}` and the assemble prompt reads the ideate
prose from `{{previous}}`.

- `IDEATE_FREE_TEXT` — free-text mode: the user's description is `{{input}}`.
- `IDEATE_GUIDED`    — guided mode: the user-supplied fields are `{{input}}`.
- `ASSEMBLE`         — turn the prose into strict v1-schema JSON, no fences.
"""

from __future__ import annotations

IDEATE_FREE_TEXT = """\
You are inventing an inhabitant of Blaboratory, a quirky virtual laboratory full \
of eccentric residents.

The user describes the character they want:
<description>
{{input}}
</description>

Invent a single, vivid, internally-consistent character that fits this \
description. Write a few rich paragraphs of character notes covering their name, \
age, sex, full physical appearance (height, build, hair color and style, eye \
color, skin tone, any distinguishing features), their occupation, their \
personality (notable traits, quirks, and how they speak), and a short backstory. \
Invent any detail the user left unspecified. Do not output JSON yet — just the \
prose notes."""

IDEATE_GUIDED = """\
You are inventing an inhabitant of Blaboratory, a quirky virtual laboratory full \
of eccentric residents.

The user has specified some fields and left the rest blank:
<fields>
{{input}}
</fields>

Honor every value the user supplied exactly, and invent the rest to form a \
single, vivid, internally-consistent character. Write a few rich paragraphs of \
character notes covering their name, age, sex, full physical appearance (height, \
build, hair color and style, eye color, skin tone, any distinguishing features), \
their occupation, their personality (notable traits, quirks, and how they \
speak), and a short backstory. Do not output JSON yet — just the prose notes."""

ASSEMBLE = """\
Convert the character notes below into a single JSON object describing the \
resident. Use ONLY the information in the notes; do not invent new facts.

<notes>
{{previous}}
</notes>

Output a JSON object with EXACTLY these fields and types:
- name: string
- age: integer
- sex: string
- height: string
- build: string
- hair_color: string
- hair_style: string
- eye_color: string
- skin_tone: string
- distinguishing_features: array of strings
- occupation: string
- personality: object with keys "traits" (array of strings), "quirks" (array of \
strings), and "speech_style" (string)
- backstory: string

Respond with JSON only — no markdown, no code fences, no commentary."""


_REGISTRY: dict[str, str] = {
    "IDEATE_FREE_TEXT": IDEATE_FREE_TEXT,
    "IDEATE_GUIDED": IDEATE_GUIDED,
    "ASSEMBLE": ASSEMBLE,
}


def get_prompt(prompt_id: str) -> str:
    """Look up a prompt template by id (raises KeyError if unknown)."""
    return _REGISTRY[prompt_id]
