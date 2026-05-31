"""SP1 — plugin backend foundation.

Exercises the registry, the ``GET /plugins`` manifest listing, the generic
action-dispatch endpoint (404/409 paths + a happy dispatch), and
``enabled_plugins`` round-tripping through the broadened config PATCH — all driven
by a **test-only** fake plugin so it doesn't depend on Summarizer (SP3).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import router as router_module
from app.apps.prattletale import store
from app.apps.prattletale.plugins import base, registry
from app.main import app

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(router_module, "get_character", lambda cid: dict(_CHARACTER))


@pytest.fixture()
def fake_plugin():
    """Register a 'faker' plugin with one echo action; remove it after the test."""
    calls: list = []

    async def run_echo(conversation_id, params):
        calls.append((conversation_id, params))
        return {"echoed": params, "conversation_id": conversation_id}

    plugin = base.Plugin(
        id="faker",
        name="Faker",
        description="A test-only plugin.",
        frontend=["apps/prattletale/plugins/faker/faker.js"],
        actions={"echo": run_echo},
        default_enabled=False,
    )
    registry.register(plugin)
    try:
        yield plugin, calls
    finally:
        registry.PLUGIN_REGISTRY.pop("faker", None)


def _create(client, *, enabled_plugins=None) -> dict:
    config = {}
    if enabled_plugins is not None:
        config["enabled_plugins"] = enabled_plugins
    r = client.post(
        "/v1/apps/prattletale/conversations",
        json={
            "title": "Late-night diner",
            "counterpart_character_id": "mara-okafor",
            "config": config,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- manifest listing ------------------------------------------------------

def test_list_plugins_includes_registered_manifest(client, fake_plugin):
    r = client.get("/v1/apps/prattletale/plugins")
    assert r.status_code == 200
    plugins = {p["id"]: p for p in r.json()["plugins"]}
    assert "faker" in plugins
    m = plugins["faker"]
    assert m["name"] == "Faker"
    assert m["actions"] == ["echo"]
    assert m["frontend"] == ["apps/prattletale/plugins/faker/faker.js"]
    assert m["default_enabled"] is False
    # The callables themselves are not serialized.
    assert "run_echo" not in str(m)


# --- dispatch happy path ---------------------------------------------------

def test_dispatch_action_returns_result(client, fake_plugin):
    _plugin, calls = fake_plugin
    conv = _create(client, enabled_plugins=["faker"])
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/plugins/faker/actions/echo",
        json={"foo": "bar"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"echoed": {"foo": "bar"}, "conversation_id": conv["id"]}
    assert calls == [(conv["id"], {"foo": "bar"})]


def test_dispatch_empty_body_ok(client, fake_plugin):
    conv = _create(client, enabled_plugins=["faker"])
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/plugins/faker/actions/echo"
    )
    assert r.status_code == 200, r.text
    assert r.json()["echoed"] == {}


# --- dispatch error paths --------------------------------------------------

def test_dispatch_unknown_conversation_404(client, fake_plugin):
    r = client.post(
        "/v1/apps/prattletale/conversations/ghost/plugins/faker/actions/echo", json={}
    )
    assert r.status_code == 404


def test_dispatch_unknown_plugin_404(client, fake_plugin):
    conv = _create(client, enabled_plugins=["faker"])
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/plugins/nope/actions/echo", json={}
    )
    assert r.status_code == 404


def test_dispatch_unknown_action_404(client, fake_plugin):
    conv = _create(client, enabled_plugins=["faker"])
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/plugins/faker/actions/nope", json={}
    )
    assert r.status_code == 404


def test_dispatch_disabled_plugin_409(client, fake_plugin):
    conv = _create(client)  # faker not in enabled_plugins
    r = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/plugins/faker/actions/echo", json={}
    )
    assert r.status_code == 409


# --- enabled_plugins round-trips through the broadened PATCH ----------------

def test_enabled_plugins_round_trips_through_patch(client, fake_plugin):
    conv = _create(client)
    assert (conv["config"].get("enabled_plugins") or []) == []

    r = client.patch(
        f"/v1/apps/prattletale/conversations/{conv['id']}",
        json={"config": {"enabled_plugins": ["faker"]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["config"]["enabled_plugins"] == ["faker"]

    # Persisted, and other config keys survive the deep merge.
    r2 = client.get(f"/v1/apps/prattletale/conversations/{conv['id']}")
    cfg = r2.json()["conversation"]["config"]
    assert cfg["enabled_plugins"] == ["faker"]
    assert cfg["context_window_turns"] == 12

    # Now the action dispatches.
    r3 = client.post(
        f"/v1/apps/prattletale/conversations/{conv['id']}/plugins/faker/actions/echo", json={}
    )
    assert r3.status_code == 200


# --- registry unit ---------------------------------------------------------

def test_registry_register_get_list(fake_plugin):
    plugin, _calls = fake_plugin
    assert registry.get_plugin("faker") is plugin
    assert plugin in registry.list_plugins()
    assert registry.get_plugin("missing") is None
