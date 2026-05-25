from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.apps.blaboratory.models import Personality, Resident, ResidentDraft


def _full_resident_kwargs() -> dict:
    return {
        "id": "abc-123",
        "schema_version": 1,
        "created_at": "2026-05-24T00:00:00+00:00",
        "updated_at": "2026-05-24T00:00:00+00:00",
        "name": "Edna Marsh",
        "age": 71,
        "sex": "female",
        "height": "5'4\"",
        "build": "slight",
        "hair_color": "silver",
        "hair_style": "tight bun",
        "eye_color": "grey",
        "skin_tone": "fair",
        "distinguishing_features": ["wire-rim spectacles", "ink-stained fingers"],
        "occupation": "retired astronomer",
        "personality": {
            "traits": ["grumpy", "meticulous"],
            "quirks": ["hoards teacups"],
            "speech_style": "clipped and dry",
        },
        "backstory": "Spent forty years mapping faint stars; now maps her teacups.",
    }


def test_valid_resident_parses():
    r = Resident(**_full_resident_kwargs())
    assert r.id == "abc-123"
    assert r.schema_version == 1
    assert r.age == 71
    assert isinstance(r.personality, Personality)
    assert r.personality.speech_style == "clipped and dry"
    assert r.distinguishing_features == ["wire-rim spectacles", "ink-stained fingers"]


def test_schema_version_defaults_to_one():
    kwargs = _full_resident_kwargs()
    del kwargs["schema_version"]
    assert Resident(**kwargs).schema_version == 1


def test_schema_version_must_be_one():
    kwargs = _full_resident_kwargs()
    kwargs["schema_version"] = 2
    with pytest.raises(ValidationError):
        Resident(**kwargs)


def test_missing_required_field_raises():
    kwargs = _full_resident_kwargs()
    del kwargs["name"]
    with pytest.raises(ValidationError):
        Resident(**kwargs)


def test_missing_personality_raises():
    kwargs = _full_resident_kwargs()
    del kwargs["personality"]
    with pytest.raises(ValidationError):
        Resident(**kwargs)


def test_negative_age_raises():
    kwargs = _full_resident_kwargs()
    kwargs["age"] = -1
    with pytest.raises(ValidationError):
        Resident(**kwargs)


def test_personality_requires_speech_style():
    with pytest.raises(ValidationError):
        Personality(traits=["x"], quirks=[])


def test_personality_lists_default_empty():
    p = Personality(speech_style="terse")
    assert p.traits == []
    assert p.quirks == []


def test_resident_draft_accepts_empty():
    d = ResidentDraft()
    assert d.name is None
    assert d.personality is None
    assert d.distinguishing_features is None


def test_resident_draft_accepts_partial():
    d = ResidentDraft(name="Theo", occupation="locksmith")
    assert d.name == "Theo"
    assert d.occupation == "locksmith"
    assert d.age is None


def test_resident_draft_accepts_full_with_nested_personality():
    d = ResidentDraft(
        name="Theo",
        personality={"traits": ["wry"], "quirks": [], "speech_style": "laconic"},
    )
    assert isinstance(d.personality, Personality)
    assert d.personality.speech_style == "laconic"


def test_resident_draft_validates_field_types():
    with pytest.raises(ValidationError):
        ResidentDraft(age=-5)
