"""Pydantic schemas for Hoodat characters (schema v1).

A **character** is a single living JSON document with a `schema_version`. The
template is organized into five sections that map onto the profile-page tabs:

- **Identity & Basics** — top-level fields (name, summary, tagline, age, sex,
  occupation).
- **Appearance** — `Appearance` block; "driver-license" style so it feeds image
  prompts cleanly, plus a `primary_outfit`.
- **Personality** — `Personality` block (traits / quirks / values / fears).
- **Background & Relationships** — `Background` block.
- **Speaking Style** — `SpeakingStyle` block: how they speak, an optional
  `voice_preset_id` referencing the project's voice-preset system, and a list of
  `dialogue_examples` (sample lines for few-shot voice priming).

`id` / `schema_version` / timestamps / `avatar_path` are server-assigned — never
produced by the LLM.

Three shapes per the project convention:
- the nested blocks,
- `Character` — the full, persisted document (all character fields required),
- `CharacterDraft` — every field Optional and no server-assigned fields; the
  validation target for raw LLM output before merge + promotion to `Character`.

`FIELD_SPECS` is the single source of truth for which fields are generatable,
their human label, kind (scalar / int / list), and which section they live in.
It drives per-field prompt registration, patch-building, and value normalization.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Appearance(BaseModel):
    height: str = ""
    build: str = ""
    hair: str = ""
    eyes: str = ""
    skin: str = ""
    distinguishing_features: list[str] = Field(default_factory=list)
    primary_outfit: str = ""


class Personality(BaseModel):
    traits: list[str] = Field(default_factory=list)
    quirks: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    fears: list[str] = Field(default_factory=list)


class Background(BaseModel):
    backstory: str = ""
    origin: str = ""
    relationships: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class SpeakingStyle(BaseModel):
    description: str = ""
    voice_preset_id: Optional[str] = None
    # Free-text sample lines that capture how the character talks; the more
    # present, the better subsequent generations match the voice (few-shot).
    dialogue_examples: list[str] = Field(default_factory=list)


class Character(BaseModel):
    """A fully-realized, persisted Hoodat character (schema v1)."""

    id: str
    schema_version: Literal[1] = 1
    created_at: str
    updated_at: str
    avatar_path: Optional[str] = None

    # Identity & Basics
    name: str
    summary: str = ""
    tagline: str = ""
    age: int = Field(default=0, ge=0)
    sex: str = ""
    occupation: str = ""

    appearance: Appearance = Field(default_factory=Appearance)
    personality: Personality = Field(default_factory=Personality)
    background: Background = Field(default_factory=Background)
    speaking_style: SpeakingStyle = Field(default_factory=SpeakingStyle)


class CharacterDraft(BaseModel):
    """Partial character used to validate raw LLM output (no server fields)."""

    name: Optional[str] = None
    summary: Optional[str] = None
    tagline: Optional[str] = None
    age: Optional[int] = Field(default=None, ge=0)
    sex: Optional[str] = None
    occupation: Optional[str] = None

    appearance: Optional[Appearance] = None
    personality: Optional[Personality] = None
    background: Optional[Background] = None
    speaking_style: Optional[SpeakingStyle] = None


# ---- generatable-field registry -------------------------------------------
# section -> field -> {label, kind}. `identity` fields live at the document top
# level; the other sections are nested blocks of the same name.
FIELD_SPECS: dict[str, dict[str, dict]] = {
    "identity": {
        "name": {"label": "name", "kind": "scalar"},
        "summary": {"label": "one-line summary", "kind": "scalar"},
        "tagline": {"label": "short tagline / motto", "kind": "scalar"},
        "age": {"label": "age in years", "kind": "int"},
        "sex": {"label": "sex", "kind": "scalar"},
        "occupation": {"label": "occupation", "kind": "scalar"},
    },
    "appearance": {
        "height": {"label": "height", "kind": "scalar"},
        "build": {"label": "body build", "kind": "scalar"},
        "hair": {"label": "hair (color and style)", "kind": "scalar"},
        "eyes": {"label": "eye color", "kind": "scalar"},
        "skin": {"label": "skin tone", "kind": "scalar"},
        "distinguishing_features": {"label": "distinguishing features", "kind": "list"},
        "primary_outfit": {"label": "commonly worn outfit", "kind": "scalar"},
    },
    "personality": {
        "traits": {"label": "personality traits", "kind": "list"},
        "quirks": {"label": "quirks", "kind": "list"},
        "values": {"label": "values they hold", "kind": "list"},
        "fears": {"label": "fears", "kind": "list"},
    },
    "background": {
        "backstory": {"label": "backstory", "kind": "scalar"},
        "origin": {"label": "place of origin", "kind": "scalar"},
        "relationships": {"label": "key relationships", "kind": "list"},
        "affiliations": {"label": "affiliations / groups", "kind": "list"},
        "skills": {"label": "notable skills", "kind": "list"},
    },
    "speaking_style": {
        "description": {"label": "description of how they speak", "kind": "scalar"},
    },
}


def field_spec(section: str, field: str) -> Optional[dict]:
    return FIELD_SPECS.get(section, {}).get(field)
