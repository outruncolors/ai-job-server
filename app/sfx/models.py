"""Data model for the normalized SFX subsystem.

A *pack* is one vendor sound set normalized into a single manifest shape. The
``binding`` discriminator records how the pack is addressed at runtime:

* ``identity`` — character-bound emote packs. Profiles are standard identity
  enums (gender x age-band) plus ``_low`` / ``_high`` pitch variants. A Hoodat
  character picks one identity; the resolver draws emotes from that profile.
* ``global`` — not character-bound. A single ``_global`` profile whose items
  carry a ``domain`` (``lewd``, and later ``footsteps``/``nature``/...). A
  Prattletale conversation opts a domain in via ``config.sfx_domains``.

Item ``path`` is relative to ``SFX_ROOT`` so vendor originals are read in place;
only pitch derivatives are generated (under ``normalized/<pack_id>/files/``).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

SFX_SCHEMA_VERSION = 1


class Identity(str, Enum):
    """Standard SFX identity: gender presentation x five age bands."""

    little_girl = "little_girl"
    little_boy = "little_boy"
    teen_girl = "teen_girl"
    teen_boy = "teen_boy"
    young_woman = "young_woman"
    young_man = "young_man"
    mature_woman = "mature_woman"
    mature_man = "mature_man"
    elderly_woman = "elderly_woman"
    elderly_man = "elderly_man"


# Vendor folder tokens -> normalized attributes.
PRESENTATION_BY_GENDER = {"Woman": "female", "Girl": "female", "Man": "male", "Boy": "male"}
AGE_BAND_BY_TOKEN = {
    "Kid": "child",
    "Teen": "teen",
    "20s": "young_adult",
    "30s": "young_adult",
    "40s": "mature_adult",
    "50s": "mature_adult",
    "60s": "elderly",
    "70s": "elderly",
}
_IDENTITY_BY_KEY = {
    ("female", "child"): Identity.little_girl,
    ("male", "child"): Identity.little_boy,
    ("female", "teen"): Identity.teen_girl,
    ("male", "teen"): Identity.teen_boy,
    ("female", "young_adult"): Identity.young_woman,
    ("male", "young_adult"): Identity.young_man,
    ("female", "mature_adult"): Identity.mature_woman,
    ("male", "mature_adult"): Identity.mature_man,
    ("female", "elderly"): Identity.elderly_woman,
    ("male", "elderly"): Identity.elderly_man,
}


def identity_for(gender: str, age_token: str) -> Optional[str]:
    """Map a vendor (gender, age) pair to a standard identity value, or None."""
    presentation = PRESENTATION_BY_GENDER.get(gender)
    age_band = AGE_BAND_BY_TOKEN.get(age_token)
    ident = _IDENTITY_BY_KEY.get((presentation, age_band))
    return ident.value if ident else None


def identity_label(identity: str) -> str:
    return identity.replace("_", " ").title()


class SfxItem(BaseModel):
    id: str
    category: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    path: str  # relative to SFX_ROOT
    duration_ms: Optional[int] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None
    weight: float = 1.0
    domain: Optional[str] = None
    source: dict[str, Any] = Field(default_factory=dict)


class SfxProfile(BaseModel):
    id: str
    display_name: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_profiles: list[str] = Field(default_factory=list)
    items: list[SfxItem] = Field(default_factory=list)


class SfxPack(BaseModel):
    schema_version: int = SFX_SCHEMA_VERSION
    type: str = "sfx_pack"
    id: str
    binding: str  # "identity" | "global"
    display_name: str = ""
    domain: Optional[str] = None
    source: dict[str, Any] = Field(default_factory=dict)
    profiles: list[SfxProfile] = Field(default_factory=list)
