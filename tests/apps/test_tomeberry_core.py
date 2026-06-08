"""Phase 2 — Tomeberry tale/concept/hierarchy/link store + routes."""

from __future__ import annotations

import pytest

from app.apps.tomeberry import store


# ---- store -----------------------------------------------------------------


def test_create_tale_scaffolds_root_and_premise():
    tale = store.create_tale({"title": "The Lost Crown", "premise": "A princess is saved."})
    assert tale["title"] == "The Lost Crown"
    assert tale["structural_root_id"]
    assert tale["premise_id"]
    # premise concept carries the body
    premise = store.get_concept(tale["id"], tale["premise_id"])
    assert premise["body"] == "A princess is saved."
    assert premise["concept_class"] == "narrative_construct"
    # root is a structural unit of type tale
    root = store.get_concept(tale["id"], tale["structural_root_id"])
    assert root["concept_class"] == "structural_unit"
    assert root["type"] == "tale"
    # workspace dir exists (MCP sandbox root)
    assert store.workspace_dir(tale["id"]).is_dir()


def test_concept_crud_and_word_count():
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    scene = store.create_concept(
        tid, {"concept_class": "structural_unit", "type": "scene", "title": "Opening", "body": "one two three"}
    )
    assert scene["metadata"]["word_count"] == 3
    got = store.get_concept(tid, scene["id"])
    assert got["title"] == "Opening"
    updated = store.update_concept(tid, scene["id"], {"body": "a b c d e"})
    assert updated["metadata"]["word_count"] == 5
    assert store.delete_concept(tid, scene["id"]) is True
    assert store.get_concept(tid, scene["id"]) is None


def test_hierarchy_tree_reflects_parenting():
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    root = tale["structural_root_id"]
    ch = store.create_concept(
        tid, {"concept_class": "structural_unit", "type": "chapter", "title": "Ch1", "parent_id": root}
    )
    sc = store.create_concept(
        tid,
        {"concept_class": "structural_unit", "type": "scene", "title": "Sc1", "parent_id": ch["id"]},
    )
    tree = store.get_hierarchy(tid)
    assert tree["root"]["id"] == root
    chapters = tree["root"]["children"]
    assert any(c["id"] == ch["id"] for c in chapters)
    chapter_node = next(c for c in chapters if c["id"] == ch["id"])
    assert any(s["id"] == sc["id"] for s in chapter_node["children"])


def test_move_reparents():
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    root = tale["structural_root_id"]
    a = store.create_concept(tid, {"concept_class": "structural_unit", "type": "chapter", "parent_id": root})
    b = store.create_concept(tid, {"concept_class": "structural_unit", "type": "chapter", "parent_id": root})
    sc = store.create_concept(tid, {"concept_class": "structural_unit", "type": "scene", "parent_id": a["id"]})
    store.move_concept(tid, sc["id"], b["id"], 0)
    assert store.get_concept(tid, sc["id"])["parent_id"] == b["id"]


def test_links_add_remove_and_cleanup_on_delete():
    tale = store.create_tale({"title": "T"})
    tid = tale["id"]
    char = store.create_concept(tid, {"concept_class": "story_entity", "type": "character", "title": "Mara"})
    plot = store.create_concept(tid, {"concept_class": "narrative_construct", "type": "plotline", "title": "Main"})
    store.add_link(tid, char["id"], {"rel": "advances", "target_id": plot["id"], "note": ""})
    assert len(store.get_concept(tid, char["id"])["links"]) == 1
    # dedup on (rel, target)
    store.add_link(tid, char["id"], {"rel": "advances", "target_id": plot["id"]})
    assert len(store.get_concept(tid, char["id"])["links"]) == 1
    # deleting the target drops the dangling link
    store.delete_concept(tid, plot["id"])
    assert store.get_concept(tid, char["id"])["links"] == []


# ---- routes ----------------------------------------------------------------


def test_routes_full_lifecycle(client):
    r = client.post("/v1/apps/tomeberry/tales", json={"title": "Quest", "premise": "Seed"})
    assert r.status_code == 201
    tid = r.json()["id"]

    # list
    assert any(t["id"] == tid for t in client.get("/v1/apps/tomeberry/tales").json()["tales"])

    # get bundles tale + hierarchy + concepts
    body = client.get(f"/v1/apps/tomeberry/tales/{tid}").json()
    assert body["tale"]["id"] == tid
    assert body["hierarchy"]["root"] is not None

    # premise update
    r = client.put(f"/v1/apps/tomeberry/tales/{tid}/premise", json={"body": "A new premise"})
    assert r.status_code == 200
    assert r.json()["body"] == "A new premise"

    # concept create + patch + move
    root = body["tale"]["structural_root_id"]
    r = client.post(
        f"/v1/apps/tomeberry/tales/{tid}/concepts",
        json={"concept_class": "structural_unit", "type": "chapter", "title": "One", "parent_id": root},
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    r = client.patch(f"/v1/apps/tomeberry/tales/{tid}/concepts/{cid}", json={"title": "Chapter One"})
    assert r.json()["title"] == "Chapter One"

    # links via routes
    r = client.post(
        f"/v1/apps/tomeberry/tales/{tid}/concepts",
        json={"concept_class": "story_entity", "type": "character", "title": "Hero"},
    )
    hero = r.json()["id"]
    r = client.post(
        f"/v1/apps/tomeberry/tales/{tid}/concepts/{hero}/links",
        json={"rel": "appears_in", "target_id": cid},
    )
    assert r.status_code == 200
    assert len(r.json()["links"]) == 1
    r = client.request(
        "DELETE", f"/v1/apps/tomeberry/tales/{tid}/concepts/{hero}/links/appears_in/{cid}"
    )
    assert r.json()["links"] == []

    # filter by class
    chars = client.get(
        f"/v1/apps/tomeberry/tales/{tid}/concepts", params={"concept_class": "story_entity"}
    ).json()["concepts"]
    assert all(c["concept_class"] == "story_entity" for c in chars)

    # delete tale
    assert client.delete(f"/v1/apps/tomeberry/tales/{tid}").status_code == 204
    assert client.get(f"/v1/apps/tomeberry/tales/{tid}").status_code == 404


def test_routes_404s(client):
    assert client.get("/v1/apps/tomeberry/tales/nope").status_code == 404
    assert client.get("/v1/apps/tomeberry/tales/nope/hierarchy").status_code == 404
    assert client.delete("/v1/apps/tomeberry/tales/nope").status_code == 404
