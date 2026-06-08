"""Phase 7 — starter templates + apply-template + export."""

from __future__ import annotations

from app.apps.tomeberry import store, templates_store
from app.cruddables.registry import get_adapter


def test_builtin_templates_seed_and_list():
    tpls = templates_store.list_templates()
    ids = {t["id"] for t in tpls}
    assert {"three_act", "heros_journey", "character_sheet"} <= ids
    # the cruddable type is registered
    assert get_adapter("tomeberry_template") is not None


def test_apply_three_act_copies_structure():
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    tpl = templates_store.get_template("three_act")
    result = store.apply_template(tid, tpl["data"])
    assert len(result["created"]) == 6
    # structure copied under the root; scenes nested under their acts
    tree = store.get_hierarchy(tid)
    parts = tree["root"]["children"]
    assert any(p["title"].startswith("Act One") for p in parts)
    act_one = next(p for p in parts if p["title"].startswith("Act One"))
    assert any(s["title"] == "Opening image" for s in act_one["children"])


def test_apply_character_sheet_creates_entity():
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    tpl = templates_store.get_template("character_sheet")
    store.apply_template(tid, tpl["data"])
    chars = store.list_concepts(tid, concept_class="story_entity", type_="character")
    assert len(chars) == 1
    assert "Want" in chars[0]["body"]


def test_export_bundles_everything():
    tale = store.create_tale({"title": "Export Me", "premise": "seed"})
    tid = tale["id"]
    store.create_concept(tid, {"concept_class": "structural_unit", "type": "scene", "title": "S"})
    bundle = store.export_tale(tid)
    assert bundle["tale"]["id"] == tid
    assert bundle["hierarchy"] is not None
    assert any(c["title"] == "S" for c in bundle["concepts"])
    assert "assistant" in bundle and "traces" in bundle


def test_template_and_export_routes(client):
    tpls = client.get("/v1/apps/tomeberry/templates").json()["templates"]
    assert len(tpls) >= 3
    tid = client.post("/v1/apps/tomeberry/tales", json={"title": "R"}).json()["id"]
    r = client.post(
        f"/v1/apps/tomeberry/tales/{tid}/apply-template", json={"template_id": "heros_journey"}
    )
    assert r.status_code == 200
    assert len(r.json()["created"]) == 12
    # export route
    exp = client.get(f"/v1/apps/tomeberry/tales/{tid}/export")
    assert exp.status_code == 200
    assert exp.json()["tale"]["id"] == tid
    # 404s
    assert client.post(
        f"/v1/apps/tomeberry/tales/{tid}/apply-template", json={"template_id": "nope"}
    ).status_code == 404
    assert client.get("/v1/apps/tomeberry/tales/nope/export").status_code == 404
