"""Pydantic schemas for Blaboratory residents.

A **resident** is a single living JSON document with a `schema_version`. The v1
field set (see design.md §"Resident schema v1") is intentionally
"driver-license" style for the physical attributes so they feed image prompts
cleanly later. `id`, `schema_version`, and the timestamps are server-assigned —
never produced by the LLM. Occupancy (which room a resident is in) is a separate
store and is deliberately *not* a field here.

Three shapes:

- `Personality` — the nested personality block (traits / quirks / speech style).
- `Resident` — the full, persisted document (all fields required).
- `ResidentDraft` — every field Optional and no server-assigned fields; this is
  the validation target for raw LLM output before it is merged with any
  user-supplied guided fields and promoted to a `Resident`.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Personality(BaseModel):
    """A resident's personality block."""

    traits: list[str] = Field(default_factory=list)
    quirks: list[str] = Field(default_factory=list)
    speech_style: str


class Resident(BaseModel):
    """A fully-realized, persisted Blaboratory resident (schema v1).

    `id` / `schema_version` / `created_at` / `updated_at` are server-assigned by
    the residents store; everything else describes the character.
    """

    id: str
    schema_version: Literal[1] = 1
    created_at: str
    updated_at: str

    name: str
    age: int = Field(..., ge=0)
    sex: str

    # "Driver-license" style physical attributes (useful for image prompts).
    height: str
    build: str
    hair_color: str
    hair_style: str
    eye_color: str
    skin_tone: str
    distinguishing_features: list[str] = Field(default_factory=list)

    occupation: str
    personality: Personality
    backstory: str


class ResidentDraft(BaseModel):
    """Partial resident, used to validate raw LLM output.

    Every character field is Optional so a partial guided submission (or a
    model that omits a field) still parses; the generator merges this with
    user-supplied fields and fills the gaps before building a `Resident`.
    Carries none of the server-assigned fields (`id` / `schema_version` /
    timestamps).
    """

    name: Optional[str] = None
    age: Optional[int] = Field(default=None, ge=0)
    sex: Optional[str] = None

    height: Optional[str] = None
    build: Optional[str] = None
    hair_color: Optional[str] = None
    hair_style: Optional[str] = None
    eye_color: Optional[str] = None
    skin_tone: Optional[str] = None
    distinguishing_features: Optional[list[str]] = None

    occupation: Optional[str] = None
    personality: Optional[Personality] = None
    backstory: Optional[str] = None
