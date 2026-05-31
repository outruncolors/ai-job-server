"""apply_items routing/report + the /v1/cruddables router (stores isolated by conftest)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.cruddables import service


def _wc(id_, name, entries=None):
    return {
        "schema_version": 1,
        "type": "wildcard",
        "id": id_,
        "name": name,
        "tags": [],
        "data": {"entries": entries or [{"text": "x"}]},
    }


def test_apply_items_mixed_report():
    items = [
        _wc("a", "A"),
        {"type": "context_item", "id": "c1", "name": "Ctx", "data": {"content": "hi"}},
        {"type": "nope", "id": "z", "name": "Z", "data": {}},  # unknown type
        {"id": "bad"},  # invalid envelope (missing type/name)
    ]
    rep = service.apply_items(items)
    assert rep["created"] == 2
    assert rep["errored"] == 2

    rep2 = service.apply_items([_wc("a", "A")])  # same id again
    assert rep2["updated"] == 1


def test_apply_items_type_mismatch_guard():
    rep = service.apply_items([_wc("a", "A")], expected_type="context_item")
    assert rep["created"] == 0
    assert rep["errored"] == 1


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def test_types_endpoint(client):
    r = client.get("/v1/cruddables/types")
    assert r.status_code == 200
    types = {t["type"] for t in r.json()["types"]}
    assert {
        "wildcard",
        "context_item",
        "image_prompt",
        "chain_sequence",
        "prompt_pal",
    } <= types


def test_export_then_extend_roundtrip(client):
    items = [_wc("rt", "Roundtrip")]
    r = client.post("/v1/cruddables/wildcard/extend", json=items)
    assert r.status_code == 200
    assert r.json()["created"] == 1

    r2 = client.get("/v1/cruddables/wildcard/export")
    assert r2.status_code == 200
    assert any(e["id"] == "rt" for e in r2.json())

    # Path type guards each item: a wildcard sent to the context_item panel errors.
    r3 = client.post("/v1/cruddables/context_item/extend", json=items)
    assert r3.json()["errored"] == 1


def test_unknown_type_404(client):
    assert client.get("/v1/cruddables/bogus/export").status_code == 404
