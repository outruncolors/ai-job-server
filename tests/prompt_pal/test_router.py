from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def _create(client, **over):
    body = {"app": "hoodat", "key": "export.bio", "title": "Bio export", "prompt": "p {{var.x}}"}
    body.update(over)
    return client.post("/v1/prompt-pal/entries", json=body)


def test_create_get_list(client):
    r = _create(client)
    assert r.status_code == 201
    entry = r.json()
    assert entry["data"]["app"] == "hoodat" and entry["data"]["key"] == "export.bio"

    got = client.get(f"/v1/prompt-pal/entries/{entry['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Bio export"

    listed = client.get("/v1/prompt-pal/entries", params={"app": "hoodat"}).json()["entries"]
    assert any(e["id"] == entry["id"] for e in listed)


def test_create_duplicate_409(client):
    assert _create(client).status_code == 201
    assert _create(client).status_code == 409


def test_get_missing_404(client):
    assert client.get("/v1/prompt-pal/entries/nope").status_code == 404


def test_put_patches_editable_only(client):
    entry = _create(client).json()
    r = client.put(
        f"/v1/prompt-pal/entries/{entry['id']}",
        json={"title": "New", "app": "evil", "key": "evil"},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["name"] == "New"
    assert updated["data"]["app"] == "hoodat"  # immutable, ignored
    assert updated["data"]["key"] == "export.bio"


def test_put_missing_404(client):
    assert client.put("/v1/prompt-pal/entries/nope", json={"title": "x"}).status_code == 404


def test_delete(client):
    entry = _create(client).json()
    assert client.delete(f"/v1/prompt-pal/entries/{entry['id']}").status_code == 200
    assert client.delete(f"/v1/prompt-pal/entries/{entry['id']}").status_code == 404


def test_preview_composes(client):
    entry = _create(client, prompt="hi {{var.who}}", variables={"who": "default"}).json()
    r = client.post(
        f"/v1/prompt-pal/entries/{entry['id']}/preview",
        json={"variables": {"who": "world"}},
    )
    assert r.status_code == 200
    assert r.json()["text"] == "hi world"


def test_tag_filter(client):
    _create(client, key="a", tags=["x"])
    _create(client, key="b", tags=["y"])
    out = client.get("/v1/prompt-pal/entries", params={"tag": "x"}).json()["entries"]
    assert {e["data"]["key"] for e in out} == {"a"}
