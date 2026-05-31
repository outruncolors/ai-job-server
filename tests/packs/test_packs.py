"""Pack store + apply tests (isolated_packs fixture in conftest patches the trees)."""

from __future__ import annotations

import json

import pytest

from app import wildcards
from app.packs import service, store


def _write_pack(root, type_name, pack_id, items, name=None, tags=None):
    d = root / type_name
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "id": pack_id,
        "name": name or pack_id,
        "description": "",
        "tags": tags or ["Pack"],
        "items": items,
    }
    (d / f"{pack_id}.json").write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _wc_item(item_id, name, entries):
    return {
        "schema_version": 1,
        "type": "wildcard",
        "id": item_id,
        "name": name,
        "tags": ["Pack"],
        "data": {"entries": entries},
    }


def test_list_and_get(isolated_packs):
    _write_pack(
        isolated_packs["builtin"], "wildcard", "p1",
        [_wc_item("c_pack_p1", "Colors", [{"text": "red"}])], name="Pack One",
    )
    packs = store.list_packs()
    assert len(packs) == 1
    s = packs[0]
    assert s["id"] == "p1"
    assert s["type"] == "wildcard"
    assert s["item_count"] == 1
    assert s["source"] == "builtin"
    doc = store.get_pack("wildcard", "p1")
    assert doc["items"][0]["id"] == "c_pack_p1"


def test_user_shadows_builtin(isolated_packs):
    _write_pack(isolated_packs["builtin"], "wildcard", "p1",
                [_wc_item("a_pack_p1", "A", [{"text": "x"}])], name="Builtin")
    _write_pack(isolated_packs["user"], "wildcard", "p1",
                [_wc_item("a_pack_p1", "A", [{"text": "y"}])], name="User")
    packs = store.list_packs()
    assert len(packs) == 1
    assert packs[0]["source"] == "user"
    assert packs[0]["name"] == "User"
    assert store.get_pack("wildcard", "p1")["name"] == "User"


def test_malformed_skipped(isolated_packs):
    d = isolated_packs["builtin"] / "wildcard"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{not json", encoding="utf-8")
    (d / "noid.json").write_text(json.dumps({"name": "x", "items": []}), encoding="utf-8")
    assert store.list_packs() == []


def test_apply_pack_writes_store_and_reapply_overwrites(isolated_packs):
    _write_pack(
        isolated_packs["builtin"], "wildcard", "p1",
        [_wc_item("colors_pack_p1", "Colors", [{"text": "red"}, {"text": "blue"}])],
    )
    report = service.apply_pack("wildcard", "p1")
    assert report["created"] == 1
    assert report["errored"] == 0
    assert report["pack"] == {"id": "p1", "type": "wildcard"}
    assert any(w["id"] == "colors_pack_p1" for w in wildcards.list_wildcards())

    # Re-applying overwrites by id (updated, not duplicated).
    report2 = service.apply_pack("wildcard", "p1")
    assert report2["updated"] == 1
    matches = [w for w in wildcards.list_wildcards() if w["id"] == "colors_pack_p1"]
    assert len(matches) == 1


def test_apply_pack_not_found(isolated_packs):
    with pytest.raises(service.PackNotFound):
        service.apply_pack("wildcard", "nope")
