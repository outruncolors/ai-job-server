from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.prompt_pal import registry, service, store


def test_get_guard_composes_and_overlays():
    registry.register(
        "testapp", "GUARDED", title="g", prompt="main {{var.x}}",
        guard={"enabled": True, "prompt": "edit {{previous}} {{var.y}}", "variables": {"y": "Y"}},
    )
    # In-code default (no store file). {{previous}} is a chain token, left intact.
    assert service.get_guard("testapp", "GUARDED") == "edit {{previous}} Y"
    # Runtime variable overlay (same as get_text).
    assert service.get_guard("testapp", "GUARDED", variables={"y": "Z"}) == "edit {{previous}} Z"


def test_get_guard_none_when_absent_disabled_or_empty():
    registry.register("testapp", "NOGUARD", title="n", prompt="p")
    assert service.get_guard("testapp", "NOGUARD") is None

    registry.register("testapp", "OFFGUARD", title="o", prompt="p",
                      guard={"enabled": False, "prompt": "x {{previous}}"})
    assert service.get_guard("testapp", "OFFGUARD") is None

    registry.register("testapp", "EMPTYGUARD", title="e", prompt="p",
                      guard={"enabled": True, "prompt": "   "})
    assert service.get_guard("testapp", "EMPTYGUARD") is None


def test_guard_put_roundtrip_and_preview():
    client = TestClient(app)
    entry = client.post("/v1/prompt-pal/entries", json={
        "app": "hoodat", "key": "qa.testguard", "title": "t", "prompt": "main"}).json()

    # PUT a guard onto the entry.
    r = client.put(f"/v1/prompt-pal/entries/{entry['id']}", json={
        "guard": {"enabled": True, "prompt": "edit {{previous}} {{var.tone}}",
                  "variables": {"tone": "calm"}}})
    assert r.status_code == 200
    assert r.json()["data"]["guard"]["prompt"] == "edit {{previous}} {{var.tone}}"

    # The stored guard wins in get_guard.
    assert service.get_guard("hoodat", "qa.testguard") == "edit {{previous}} calm"

    # Preview the guard, overlaying a variable.
    pv = client.post(f"/v1/prompt-pal/entries/{entry['id']}/preview",
                     json={"variables": {"tone": "angry"}, "target": "guard"})
    assert pv.status_code == 200
    assert pv.json()["text"] == "edit {{previous}} angry"


def test_preview_guard_404_without_guard():
    client = TestClient(app)
    e = client.post("/v1/prompt-pal/entries", json={
        "app": "hoodat", "key": "qa.noguard", "title": "t", "prompt": "x"}).json()
    r = client.post(f"/v1/prompt-pal/entries/{e['id']}/preview", json={"target": "guard"})
    assert r.status_code == 404


def test_seed_backfills_guard_onto_legacy_entry():
    registry.register("testapp", "LEGACYGUARD", title="L", prompt="body",
                      guard={"enabled": True, "prompt": "edit {{previous}}"})
    # A pre-guard install's stored file has no `guard` key at all.
    d = store.PROMPT_PAL_DIR
    d.mkdir(parents=True, exist_ok=True)
    legacy = {"id": "legacy1", "schema_version": 1, "created_at": "x", "updated_at": "x",
              "app": "testapp", "key": "LEGACYGUARD", "title": "L", "description": "",
              "tags": [], "prompt": "body", "variables": {}}
    (d / "legacy1.json").write_text(json.dumps(legacy), encoding="utf-8")

    registry.seed_registered()
    after = store.get_by_app_key("testapp", "LEGACYGUARD")
    assert after["id"] == "legacy1"  # same entry, not a duplicate
    assert after["data"]["guard"]["prompt"] == "edit {{previous}}"


def test_seed_does_not_clobber_disabled_guard():
    registry.register("testapp", "KEEPOFF", title="K", prompt="b",
                      guard={"enabled": True, "prompt": "g {{previous}}"})
    # User disabled the guard — a `guard` object is present on disk.
    store.create_entry({"app": "testapp", "key": "KEEPOFF", "title": "K", "prompt": "b",
                        "guard": {"enabled": False, "prompt": ""}})
    registry.seed_registered()
    after = store.get_by_app_key("testapp", "KEEPOFF")
    assert after["data"]["guard"]["enabled"] is False  # the disable survived re-seeding


def test_create_with_guard():
    client = TestClient(app)
    r = client.post("/v1/prompt-pal/entries", json={
        "app": "hoodat", "key": "qa.created", "title": "t", "prompt": "p",
        "guard": {"enabled": True, "prompt": "g {{previous}}"}})
    assert r.status_code == 201
    assert r.json()["data"]["guard"]["prompt"] == "g {{previous}}"
