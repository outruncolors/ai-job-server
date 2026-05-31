from __future__ import annotations

from app.cruddables.adapters.wildcard import WildcardAdapter
from app.cruddables.envelope import Cruddable
from app.cruddables.service import apply_items


def _env(id_, name, entries, tags=None):
    return Cruddable(
        type="wildcard", id=id_, name=name, tags=tags or [],
        data={"entries": entries},
    )


def test_create_uses_slug_id():
    import app.wildcards as wildcards
    wc = wildcards.create_wildcard("Hair Colors", [{"text": "blonde"}], "desc")
    assert wc["id"] == "hair_colors"
    assert wc["type"] == "wildcard"
    assert wc["data"]["entries"] == [{"text": "blonde"}]
    assert wc["name"] == "Hair Colors"


def test_create_uniquifies_slug():
    import app.wildcards as wildcards
    a = wildcards.create_wildcard("Colors", [{"text": "red"}])
    b = wildcards.create_wildcard("Colors", [{"text": "blue"}])
    assert a["id"] == "colors"
    assert b["id"] == "colors_2"


def test_adapter_round_trip_and_explicit_upsert():
    ad = WildcardAdapter()
    action, eid = ad.upsert_envelope(_env("moods_pack_x", "Moods", [{"text": "calm"}], ["Pack"]))
    assert action == "created" and eid == "moods_pack_x"
    got = ad.get_envelope("moods_pack_x")
    assert got is not None and got.data["entries"] == [{"text": "calm"}]
    assert got.tags == ["Pack"]
    # re-upsert same id overwrites (not a duplicate row)
    action2, _ = ad.upsert_envelope(_env("moods_pack_x", "Moods", [{"text": "tense"}], ["Pack"]))
    assert action2 == "updated"
    assert ad.count() == 1
    assert ad.get_envelope("moods_pack_x").data["entries"] == [{"text": "tense"}]


def test_legacy_doc_normalized_on_read():
    import app.wildcards as wildcards
    wildcards._write_index([
        {"id": "abc123", "name": "Old", "description": "", "entries": [{"text": "x"}]},
    ])
    items = wildcards.list_wildcards()
    assert items[0]["type"] == "wildcard"
    assert items[0]["data"]["entries"] == [{"text": "x"}]
    assert items[0]["tags"] == []


def test_apply_items_reports():
    rep = apply_items([
        _env("a_pack_p", "A", [{"text": "1"}]).model_dump(),
        _env("b_pack_p", "B", [{"text": "2"}]).model_dump(),
        {"type": "nope", "id": "z", "name": "Z", "data": {}},
    ])
    assert rep["created"] == 2
    assert rep["errored"] == 1
