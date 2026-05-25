from __future__ import annotations

import pytest

from app.apps.blaboratory import residents_store, rooms


@pytest.fixture(autouse=True)
def tmp_stores(tmp_path, monkeypatch):
    """Redirect both Blaboratory stores at tmp dirs for each test."""
    monkeypatch.setattr(residents_store, "RESIDENTS_DIR", tmp_path / "residents")
    monkeypatch.setattr(rooms, "OCCUPANCY_PATH", tmp_path / "occupancy.json")


def _char_fields() -> dict:
    return {
        "name": "Edna Marsh",
        "age": 71,
        "sex": "female",
        "height": "5'4\"",
        "build": "slight",
        "hair_color": "silver",
        "hair_style": "tight bun",
        "eye_color": "grey",
        "skin_tone": "fair",
        "distinguishing_features": ["wire-rim spectacles"],
        "occupation": "retired astronomer",
        "personality": {"traits": ["grumpy"], "quirks": [], "speech_style": "dry"},
        "backstory": "Mapped faint stars for forty years.",
    }


# ---- residents store ----

def test_create_then_get_roundtrip():
    created = residents_store.create_resident(_char_fields())
    assert created["id"]
    assert created["schema_version"] == 1
    assert created["created_at"] == created["updated_at"]
    assert created["name"] == "Edna Marsh"

    fetched = residents_store.get_resident(created["id"])
    assert fetched == created


def test_get_missing_returns_none():
    assert residents_store.get_resident("nope") is None


def test_list_residents():
    assert residents_store.list_residents() == []
    a = residents_store.create_resident(_char_fields())
    b = residents_store.create_resident(_char_fields())
    ids = {r["id"] for r in residents_store.list_residents()}
    assert ids == {a["id"], b["id"]}


def test_create_rejects_invalid_fields():
    bad = _char_fields()
    del bad["backstory"]
    with pytest.raises(Exception):
        residents_store.create_resident(bad)


def test_save_resident_bumps_updated_at():
    created = residents_store.create_resident(_char_fields())
    created["occupation"] = "amateur clockmaker"
    saved = residents_store.save_resident(created)
    assert saved["occupation"] == "amateur clockmaker"
    assert saved["updated_at"] >= created["updated_at"]
    assert residents_store.get_resident(created["id"])["occupation"] == "amateur clockmaker"


def test_save_requires_id():
    with pytest.raises(ValueError):
        residents_store.save_resident({"name": "x"})


def test_delete_resident():
    created = residents_store.create_resident(_char_fields())
    assert residents_store.delete_resident(created["id"]) is True
    assert residents_store.get_resident(created["id"]) is None
    assert residents_store.delete_resident(created["id"]) is False


# ---- rooms / occupancy ----

def test_list_occupancy_always_16_empty():
    occ = rooms.list_occupancy()
    assert len(occ) == 16
    assert set(occ.keys()) == {str(i) for i in range(1, 17)}
    assert all(v is None for v in occ.values())


def test_set_and_get_occupant():
    rooms.set_occupant(3, "resident-abc")
    assert rooms.get_room(3) == "resident-abc"
    assert rooms.is_empty(3) is False
    assert rooms.is_empty(4) is True
    assert rooms.list_occupancy()["3"] == "resident-abc"


def test_set_on_occupied_raises():
    rooms.set_occupant(5, "first")
    with pytest.raises(ValueError):
        rooms.set_occupant(5, "second")
    assert rooms.get_room(5) == "first"


def test_clear_room_then_reuse():
    rooms.set_occupant(7, "x")
    rooms.clear_room(7)
    assert rooms.is_empty(7) is True
    rooms.set_occupant(7, "y")  # no longer raises
    assert rooms.get_room(7) == "y"


@pytest.mark.parametrize("bad", [0, 17, -1, 100])
def test_out_of_range_raises(bad):
    with pytest.raises(ValueError):
        rooms.set_occupant(bad, "x")
    with pytest.raises(ValueError):
        rooms.get_room(bad)
    with pytest.raises(ValueError):
        rooms.clear_room(bad)
