from __future__ import annotations

import pytest

from app.prompt_pal import store


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")


def _fields(**over) -> dict:
    base = {
        "app": "hoodat",
        "key": "IDEATE",
        "title": "Ideate",
        "description": "desc",
        "tags": ["t"],
        "prompt": "hello {{var.x}}",
        "variables": {"x": "X"},
    }
    base.update(over)
    return base


def test_create_assigns_server_fields():
    entry = store.create_entry(_fields())
    assert entry["id"]
    assert entry["schema_version"] == 1
    assert entry["created_at"] and entry["updated_at"]
    assert entry["data"]["app"] == "hoodat" and entry["data"]["key"] == "IDEATE"


def test_get_and_get_by_app_key():
    created = store.create_entry(_fields())
    assert store.get_entry(created["id"])["name"] == "Ideate"
    assert store.get_by_app_key("hoodat", "IDEATE")["id"] == created["id"]
    assert store.get_by_app_key("hoodat", "MISSING") is None
    assert store.get_entry("nope") is None


def test_list_entries():
    store.create_entry(_fields(key="A"))
    store.create_entry(_fields(key="B"))
    keys = {e["data"]["key"] for e in store.list_entries()}
    assert keys == {"A", "B"}


def test_update_only_patchable_fields():
    created = store.create_entry(_fields())
    updated = store.update_entry(
        created["id"],
        title="New",
        prompt="changed",
        app="evil",  # must be ignored (immutable)
        key="evil",  # must be ignored (immutable)
    )
    assert updated["name"] == "New"
    assert updated["data"]["prompt"] == "changed"
    assert updated["data"]["app"] == "hoodat"
    assert updated["data"]["key"] == "IDEATE"
    assert updated["updated_at"] >= created["updated_at"]


def test_update_missing_returns_none():
    assert store.update_entry("nope", title="x") is None


def test_delete():
    created = store.create_entry(_fields())
    assert store.delete_entry(created["id"]) is True
    assert store.delete_entry(created["id"]) is False
    assert store.get_entry(created["id"]) is None


def test_node_for_id_feeds_compose():
    from app.prompt_pal.compose import compose

    created = store.create_entry(_fields(prompt="hi {{var.n}}", variables={"n": "there"}))
    assert compose({"prompt_id": created["id"]}, store=store.node_for_id) == "hi there"
    assert store.node_for_id("nope") is None
