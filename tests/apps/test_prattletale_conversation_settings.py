"""SP2 — conversation settings API (editable metadata + behaviour config).

Drives the broadened ``PATCH /conversations/{id}`` over ``TestClient``; asserts
metadata + nested/flat config patches persist and that ``context_window_turns``
actually changes the window ``build_context`` slices.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import generator, router as router_module, store
from app.main import app

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(router_module, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))


@pytest.fixture()
def client():
    return TestClient(app)


def _seed() -> str:
    conv = store.create_conversation({
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
        "role_instructions": "Stay in character.",
        "device_user": {"display_name": "You", "persona": "A regular."},
    })
    return conv["id"]


def _patch(client, cid, body):
    return client.patch(f"/v1/apps/prattletale/conversations/{cid}", json=body)


# --- metadata ---------------------------------------------------------------

def test_patch_metadata_persists_and_bumps_updated_at(client):
    cid = _seed()
    before = store.get_conversation(cid)["updated_at"]
    r = _patch(client, cid, {
        "scenario": "Now it's dawn.",
        "role_instructions": "Be terse.",
        "device_user": {"display_name": "Sam", "persona": "A night-shift nurse."},
    })
    assert r.status_code == 200, r.text
    conv = store.get_conversation(cid)
    assert conv["scenario"] == "Now it's dawn."
    assert conv["role_instructions"] == "Be terse."
    assert conv["device_user"]["persona"] == "A night-shift nurse."
    assert conv["device_user"]["display_name"] == "Sam"
    assert conv["updated_at"] >= before


def test_patch_title(client):
    cid = _seed()
    _patch(client, cid, {"title": "Dawn diner"})
    assert store.get_conversation(cid)["title"] == "Dawn diner"


# --- behaviour config -------------------------------------------------------

def test_patch_context_window_changes_built_window(client):
    cid = _seed()
    for n in range(1, 6):
        store.append_user_turn(cid, [{"type": "dialogue", "text": str(n)}])

    r = _patch(client, cid, {"config": {"context_window_turns": 2}})
    assert r.status_code == 200, r.text
    conv = store.get_conversation(cid)
    assert conv["config"]["context_window_turns"] == 2
    # the voice/variety flags are NOT clobbered by the partial config patch
    assert conv["config"]["variety_pass_enabled"] is True
    assert conv["config"]["voice_enabled"] is False

    ctx = generator.build_context(conv, dict(_CHARACTER), store.get_transcript(cid))
    assert ctx["transcript"].splitlines() == ["[User] 4", "[User] 5"]


def test_patch_context_window_zero_or_negative_422(client):
    cid = _seed()
    assert _patch(client, cid, {"config": {"context_window_turns": 0}}).status_code == 422
    assert _patch(client, cid, {"config": {"context_window_turns": -3}}).status_code == 422
    # flat form is validated too
    assert _patch(client, cid, {"context_window_turns": 0}).status_code == 422


def test_flat_toggle_still_flips_via_same_endpoint(client):
    """Back-compat: the Phase-1 frontend sends flat ``{voice_enabled: …}``."""
    cid = _seed()
    r = _patch(client, cid, {"voice_enabled": True})
    assert r.status_code == 200
    assert store.get_conversation(cid)["config"]["voice_enabled"] is True
    # unrelated config keys preserved
    assert store.get_conversation(cid)["config"]["context_window_turns"] == 12


def test_nested_config_wins_over_flat_on_conflict(client):
    cid = _seed()
    _patch(client, cid, {"voice_enabled": False, "config": {"voice_enabled": True}})
    assert store.get_conversation(cid)["config"]["voice_enabled"] is True


def test_patch_missing_conversation_404(client):
    assert _patch(client, "nope", {"scenario": "x"}).status_code == 404
