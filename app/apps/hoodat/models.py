"""Pydantic schemas for Hoodat characters (schema v2).

A **character** is a single living JSON document with a `schema_version`. The
template is organized into sections that map onto the profile-page tabs:

- **Identity & Basics** — top-level fields (name, summary, tagline, age, sex,
  occupation).
- **Appearance** — `Appearance` block, surfaced as three sub-sections: *Basics*
  (always-visible traits incl. hair color/details, eye color/details), *Nude*
  (private-area fields — shared, plus male-only and female-only, gated on `sex`
  in the UI; kept FLAT on the block so per-field generation works unchanged), and
  *Clothed* (a list of `outfits`, each a line-item with garment slots; one is
  marked `primary` and feeds the avatar image prompt).
- **Personality** — `Personality` block (traits / quirks / values / fears).
- **Background & Relationships** — `Background` block.
- **Speaking Style** — `SpeakingStyle` block: how they speak, an optional
  `voice_preset_id` referencing the project's voice-preset system, and a list of
  `dialogue_examples` (sample lines for few-shot voice priming).
- **Experiences** — top-level `experiences` list: formative events with a
  positive/negative `valence`, split into `{{var.experiences_positive}}` /
  `{{var.experiences_negative}}` for later formatting.
- **Q&A** — top-level `qa` list of interview-style `{question, answer}` pairs
  (AliChat-style roleplay exemplars; answers are spoken-only / TTS-friendly).
  Frontend-owned (collect → PUT wholesale), like experiences/dialogue examples.

`id` / `schema_version` / timestamps / `avatar_path` are server-assigned — never
produced by the LLM.

Three shapes per the project convention:
- the nested blocks,
- `Character` — the full, persisted document (all character fields required),
- `CharacterDraft` — every field Optional and no server-assigned fields; the
  validation target for raw LLM output before merge + promotion to `Character`.

`FIELD_SPECS` is the single source of truth for which scalar/list fields are
generatable, their human label, kind (scalar / int / list), and which section
they live in. It drives per-field prompt registration, patch-building, and value
normalization. (Outfits and experiences are lists-of-objects, handled specially
like dialogue examples — NOT in `FIELD_SPECS`.)

**Migration (v1 → v2):** old `Appearance` docs carry flat `hair` / `eyes` /
`primary_outfit`. A `model_validator(mode="before")` on `Appearance` hoists those
into the new shape (mirrors `ChainStep`'s v1-shorthand hoist in
`app/chain/models.py`). It only fires when `Appearance(**data)` is constructed
(i.e. on write); the store additionally normalizes on read so the UI never sees
the legacy shape.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Garment slots on an outfit (order = avatar/render assembly order).
OUTFIT_SLOTS = ("top", "bottoms", "underwear", "socks_shoes", "accessories")


class Experience(BaseModel):
    """A formative event in the character's history, tagged by emotional valence."""

    description: str = ""
    valence: Literal["positive", "negative"] = "positive"


class QAPair(BaseModel):
    """An interview-style question + the character's in-voice answer (AliChat).
    Q&A pairs are the character's roleplay exemplars: spoken-only answers that
    sound right over TTS and shape how the character talks elsewhere."""

    question: str = ""
    answer: str = ""


class Outfit(BaseModel):
    """A single named outfit, broken into garment slots. Exactly one outfit on a
    character should be `primary` (the one that feeds the avatar image prompt)."""

    name: str = ""
    top: str = ""
    bottoms: str = ""
    underwear: str = ""
    socks_shoes: str = ""
    accessories: str = ""
    primary: bool = False


class Appearance(BaseModel):
    # --- Basics (always visible) ---
    height: str = ""
    build: str = ""
    skin: str = ""
    hair_color: str = ""
    hair_details: str = ""
    eye_color: str = ""
    eye_details: str = ""
    distinguishing_features: list[str] = Field(default_factory=list)
    # --- Nude: shared (all sexes) ---
    body_hair: str = ""
    pubic_hair: str = ""
    buttocks: str = ""
    lips: str = ""
    hands: str = ""
    feet: str = ""
    # --- Nude: male-only (UI-gated on sex) ---
    penis: str = ""
    testicles: str = ""
    # --- Nude: female-only (UI-gated on sex) ---
    breasts: str = ""
    vulva: str = ""
    # --- Clothed ---
    outfits: list[Outfit] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy(cls, data):
        """Hoist v1 flat fields (`hair`/`eyes`/`primary_outfit`) into the v2 shape.

        Guarded so it never clobbers an already-set v2 value, and pops the legacy
        keys either way so they don't linger on the persisted doc.
        """
        if not isinstance(data, dict):
            return data
        legacy_hair = data.pop("hair", None)
        if legacy_hair and not data.get("hair_color") and not data.get("hair_details"):
            data["hair_color"] = legacy_hair
        legacy_eyes = data.pop("eyes", None)
        if legacy_eyes and not data.get("eye_color"):
            data["eye_color"] = legacy_eyes
        legacy_outfit = data.pop("primary_outfit", None)
        if legacy_outfit and not data.get("outfits"):
            data["outfits"] = [{"name": "Primary", "top": legacy_outfit, "primary": True}]
        return data


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


class VoiceFeel(BaseModel):
    """A character's stable dialogue *fingerprint* — small levers that interact to
    make the character recognizable in actual text-message dialogue (consumed by
    Prattletale's turn prompt, which can override any field per-conversation).

    Additive/optional like ``SpeakingStyle.sfx``: absent on existing characters,
    frontend-owned (PUT wholesale like ``dialogue_examples``), and **not** in
    ``FIELD_SPECS`` (not LLM-generatable for now). When ``enabled`` is False the
    character contributes no feel fields (a per-conversation override can still
    supply them)."""

    enabled: bool = False
    cadence: str = ""
    lexicon: str = ""
    conversational_tactic: str = ""
    subtext_rules: str = ""
    avoid: str = ""
    examples: list[str] = Field(default_factory=list)


class SpeakingStyle(BaseModel):
    description: str = ""
    voice_preset_id: Optional[str] = None
    # Free-text sample lines that capture how the character talks; the more
    # present, the better subsequent generations match the voice (few-shot).
    dialogue_examples: list[str] = Field(default_factory=list)
    # SFX/Emotes binding: {"emotes_identity": "<Identity value>", "enabled": bool}.
    # Optional — absent on existing characters; not LLM-generatable (not in FIELD_SPECS).
    sfx: Optional[dict] = None
    # Stable dialogue fingerprint (see VoiceFeel). Optional/additive.
    voice_feel: Optional[VoiceFeel] = None


class Character(BaseModel):
    """A fully-realized, persisted Hoodat character (schema v2)."""

    id: str
    schema_version: Literal[2] = 2
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
    experiences: list[Experience] = Field(default_factory=list)
    # Interview-style Q&A exemplars (frontend-owned list, like experiences).
    qa: list[QAPair] = Field(default_factory=list)


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
    experiences: Optional[list[Experience]] = None


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
    # NOTE: nude fields are FLAT here (not nested under `appearance.nude`) so the
    # two-level per-field generate path (`{section: {field: value}}`) works
    # unchanged. The UI gates them on `sex`. `outfits` is a list-of-objects and is
    # intentionally NOT here (handled like dialogue examples).
    "appearance": {
        # Basics
        "height": {"label": "height", "kind": "scalar"},
        "build": {"label": "body build", "kind": "scalar"},
        "skin": {"label": "skin tone", "kind": "scalar"},
        "hair_color": {"label": "hair color", "kind": "scalar"},
        "hair_details": {"label": "hair style / details", "kind": "scalar"},
        "eye_color": {"label": "eye color", "kind": "scalar"},
        "eye_details": {"label": "eye details", "kind": "scalar"},
        "distinguishing_features": {"label": "distinguishing features", "kind": "list"},
        # Nude — shared
        "body_hair": {"label": "body hair", "kind": "scalar"},
        "pubic_hair": {"label": "pubic hair", "kind": "scalar"},
        "buttocks": {"label": "buttocks", "kind": "scalar"},
        "lips": {"label": "lips", "kind": "scalar"},
        "hands": {"label": "hands", "kind": "scalar"},
        "feet": {"label": "feet", "kind": "scalar"},
        # Nude — male-only
        "penis": {"label": "penis", "kind": "scalar"},
        "testicles": {"label": "testicles", "kind": "scalar"},
        # Nude — female-only
        "breasts": {"label": "breasts", "kind": "scalar"},
        "vulva": {"label": "vulva", "kind": "scalar"},
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
