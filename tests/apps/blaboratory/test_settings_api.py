"""Sim settings API (GET/PUT /v1/apps/blaboratory/settings)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.apps.blaboratory import settings_store
from app.apps.blaboratory.router import router

URL = "/v1/apps/blaboratory/settings"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / "settings.json")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_returns_defaults(client):
    r = client.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(settings_store._DEFAULTS)
    assert body["tick_interval_seconds"] == settings_store._DEFAULTS["tick_interval_seconds"]


def test_put_partial_updates_and_roundtrips(client):
    r = client.put(URL, json={"tick_interval_seconds": 60})
    assert r.status_code == 200
    body = r.json()
    assert body["tick_interval_seconds"] == 60
    assert body["max_memory_items"] == settings_store._DEFAULTS["max_memory_items"]
    assert client.get(URL).json()["tick_interval_seconds"] == 60


def test_put_empty_body_is_noop(client):
    r = client.put(URL, json={})
    assert r.status_code == 200
    assert r.json() == settings_store.get_settings()


def test_put_out_of_range_returns_422_with_field(client):
    r = client.put(URL, json={"tick_interval_seconds": 0})
    assert r.status_code == 422
    assert r.json()["detail"]["field"] == "tick_interval_seconds"


def test_put_non_numeric_returns_422(client):
    # Fails Pydantic model validation before reaching the store.
    r = client.put(URL, json={"max_memory_items": "lots"})
    assert r.status_code == 422
