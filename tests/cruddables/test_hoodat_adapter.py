from __future__ import annotations

import json

from app.apps.hoodat import characters_store as cs
from app.cruddables.adapters.hoodat_character import HoodatCharacterAdapter
from app.cruddables.envelope import Cruddable
from app.cruddables.service import apply_items


def _env(id_, name, data=None, tags=None):
    return Cruddable(
        type="hoodat_character", id=id_, name=name, tags=tags or [],
        data=data or {},
    )


def test_create_uses_slug_id_and_writes_envelope_on_disk():
    char = cs.create_character({"name": "Ada Lovelace", "summary": "pioneer"})
    assert char["id"] == "ada_lovelace"
    assert char["schema_version"] == 2  # flat body keeps its own version
    # on disk it is an envelope with the body under `data`
    raw = json.loads((cs.CHARACTERS_DIR / "ada_lovelace.json").read_text())
    assert raw["type"] == "hoodat_character"
    assert raw["schema_version"] == 1
    assert raw["name"] == "Ada Lovelace"
    assert raw["description"] == "pioneer"  # mirrors summary for the list view
    assert raw["data"]["content_version"] == 2
    assert raw["data"]["summary"] == "pioneer"
    assert "name" not in raw["data"]  # name lives only on the envelope meta


def test_create_uniquifies_slug():
    a = cs.create_character({"name": "Ada"})
    b = cs.create_character({"name": "Ada"})
    assert a["id"] == "ada"
    assert b["id"] == "ada_2"


def test_flat_body_api_unchanged():
    char = cs.create_character({"name": "Grace", "appearance": {"hair_color": "silver"}})
    got = cs.get_character(char["id"])
    assert "type" not in got and "data" not in got  # callers still see the flat body
    assert got["appearance"]["hair_color"] == "silver"
    # nested-section deep-merge still works
    cs.update_character_fields(char["id"], {"appearance": {"build": "tall"}})
    after = cs.get_character(char["id"])
    assert after["appearance"]["hair_color"] == "silver"  # untouched
    assert after["appearance"]["build"] == "tall"


def test_adapter_round_trip_and_explicit_upsert():
    ad = HoodatCharacterAdapter()
    action, eid = ad.upsert_envelope(
        _env("zed_pack_x", "Zed", {"summary": "packed", "appearance": {"build": "lean"}}, ["Pack"])
    )
    assert action == "created" and eid == "zed_pack_x"
    got = ad.get_envelope("zed_pack_x")
    assert got is not None
    assert got.tags == ["Pack"]
    assert got.data["summary"] == "packed"
    assert got.data["appearance"]["build"] == "lean"
    # re-upsert same id overwrites (not a duplicate row) and preserves created_at
    created_at = got.created_at
    action2, _ = ad.upsert_envelope(
        _env("zed_pack_x", "Zed", {"summary": "repacked"}, ["Pack"])
    )
    assert action2 == "updated"
    assert ad.get_envelope("zed_pack_x").data["summary"] == "repacked"
    assert ad.get_envelope("zed_pack_x").created_at == created_at


def test_save_preserves_tags():
    ad = HoodatCharacterAdapter()
    ad.upsert_envelope(_env("tagged_pack_y", "Tagged", {"summary": "s"}, ["Pack", "demo"]))
    # editing through the flat-body API must not drop the envelope tags
    cs.update_character_fields("tagged_pack_y", {"summary": "edited"})
    env = cs.get_envelope("tagged_pack_y")
    assert env["tags"] == ["Pack", "demo"]
    assert env["data"]["summary"] == "edited"


def test_legacy_flat_doc_normalized_on_read():
    cs.CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    (cs.CHARACTERS_DIR / "legacy_uuid.json").write_text(json.dumps({
        "id": "legacy_uuid", "schema_version": 1,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
        "name": "Lou",
        "appearance": {"hair": "blonde", "primary_outfit": "tube top"},
    }), encoding="utf-8")
    env = HoodatCharacterAdapter().get_envelope("legacy_uuid")
    assert env.type == "hoodat_character"
    assert env.data["content_version"] == 2
    assert env.data["appearance"]["hair_color"] == "blonde"  # v1 -> v2 migrated
    assert env.created_at == "2024-01-01T00:00:00+00:00"
    # flat-body read also migrates
    body = cs.get_character("legacy_uuid")
    assert body["appearance"]["outfits"][0]["top"] == "tube top"


def test_apply_items_routes_hoodat_character():
    rep = apply_items([
        _env("c1_pack_p", "C1", {"summary": "one"}).model_dump(),
        _env("c2_pack_p", "C2", {"summary": "two"}).model_dump(),
    ], expected_type="hoodat_character")
    assert rep["created"] == 2
    assert cs.get_character("c1_pack_p")["summary"] == "one"


def test_migrate_native_reshapes_legacy():
    out = HoodatCharacterAdapter().migrate_native({
        "id": "u1", "schema_version": 1, "name": "Mig",
        "created_at": "t", "updated_at": "t",
        "appearance": {"hair": "red"},
    })
    assert out["type"] == "hoodat_character"
    assert out["id"] == "u1"
    assert out["data"]["content_version"] == 2
    assert out["data"]["appearance"]["hair_color"] == "red"
    assert "name" not in out["data"]
