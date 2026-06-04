"""Prattletale ↔ memory integration tests.

Covers both halves of the integration:

- **Retrieval** — the turn chain's ``{{memory}}`` config is scoped to
  ``character:<counterpart>`` + ``session:<conversation>`` and actually surfaces a
  seeded memory (and stays empty / fail-soft when there's nothing to recall).
- **Write** — the Remember plugin's ``remember`` (verbatim) and ``gist`` actions,
  and the Summarizer's opt-in "also save to memory", each persist through the
  memory **service** to the right scope on disk.

Memory storage is redirected to a tmp dir by the autouse ``patch_memory_base``
fixture in ``tests/conftest.py``; here we additionally isolate the Prattletale
store and stub the LLM seam (no real model calls).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.apps.prattletale import generator, store
from app.apps.prattletale import prompts as pt_prompts  # noqa: F401 — registers turn prompt
from app.apps.prattletale import router as router_module
from app.apps.prattletale.plugins import registry as plugin_registry
from app.apps.prattletale.plugins.memory import plugin as memory_plugin
from app.chain.models import ChainLLMConfig, MemoryStepConfig
from app.chain.steps.llm import _retrieve_memory_block
from app.main import app
from app.memory import MemoryScope, MemoryWriteRequest, get_service

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}
_GOOD = "[say] where else would i be"
BASE = "/v1/apps/prattletale"


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # Make sure the plugin registry is populated (registration is import-time, but
    # seed is idempotent and guards against import order).
    plugin_registry.seed_plugins()
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(router_module, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(memory_plugin, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: SimpleNamespace(chat_template_kwargs=None,
                                model_copy=lambda **k: SimpleNamespace(chat_template_kwargs={})),
    )

    async def fake_chain(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(_GOOD, encoding="utf-8")

    monkeypatch.setattr(generator, "execute_chain_job", fake_chain)


# ---- retrieval -------------------------------------------------------------

def test_turn_request_carries_memory_config_scoped_to_character_and_session():
    context_vars = {"transcript": "[User] what's my dog's name", "_mem_query": "dog name"}
    req = generator.build_turn_request(
        context_vars,
        ChainLLMConfig(api_base="http://x", model="m"),
        variety=False,
        counterpart_id="mara-okafor",
        session_id="conv-123",
    )
    turn_step = req.steps[0]
    assert turn_step.id == "turn"
    cfg = turn_step.alternatives[0].memory
    assert isinstance(cfg, MemoryStepConfig) and cfg.enabled
    scope_ids = {(s["scope_type"], s["scope_id"]) for s in cfg.scopes}
    assert ("character", "{{var.counterpart_id}}") in scope_ids
    assert ("session", "{{var.session_id}}") in scope_ids
    # Broader buckets: app-wide + global facts (e.g. the user's name) reach every character.
    assert ("app", "prattletale") in scope_ids
    assert ("global", "global") in scope_ids
    # The caller-side variables resolve those templates at run time.
    assert req.variables["counterpart_id"] == "mara-okafor"
    assert req.variables["session_id"] == "conv-123"
    assert req.variables["mem_query"] == "dog name"


async def test_turn_retrieval_surfaces_seeded_character_memory():
    svc = get_service()
    await svc.write(MemoryWriteRequest(
        title="Pet", body="I have a dog named Pixel.",
        scope=MemoryScope(scope_type="character", scope_id=_CHARACTER["id"]),
    ))
    cfg = MemoryStepConfig(
        enabled=True, query="{{var.mem_query}}",
        scopes=[
            {"scope_type": "character", "scope_id": "{{var.counterpart_id}}"},
            {"scope_type": "session", "scope_id": "{{var.session_id}}"},
        ],
    )
    block = await _retrieve_memory_block(
        cfg,
        request=SimpleNamespace(input="what's my dog's name"),
        text_output="", context="",
        step=SimpleNamespace(name="turn"), step_index=1,
        step_inputs={}, step_outputs={},
        variables={"mem_query": "dog", "counterpart_id": _CHARACTER["id"], "session_id": "conv-x"},
    )
    assert "Pixel" in block
    assert "character/mara-okafor" in block


async def test_turn_retrieval_surfaces_global_memory():
    # A global fact (e.g. the user's name) reaches a character via the turn's
    # broadened scope set, even with no character/session memory of its own.
    svc = get_service()
    await svc.write(MemoryWriteRequest(
        title="User name", body="The user's name is Jason.",
        scope=MemoryScope(scope_type="global", scope_id="global"),
    ))
    cfg = MemoryStepConfig(
        enabled=True, query="{{var.mem_query}}",
        scopes=[
            {"scope_type": "character", "scope_id": "{{var.counterpart_id}}"},
            {"scope_type": "session", "scope_id": "{{var.session_id}}"},
            {"scope_type": "app", "scope_id": "prattletale"},
            {"scope_type": "global", "scope_id": "global"},
        ],
    )
    block = await _retrieve_memory_block(
        cfg,
        request=SimpleNamespace(input="what's my name"),
        text_output="", context="",
        step=SimpleNamespace(name="turn"), step_index=1,
        step_inputs={}, step_outputs={},
        variables={"mem_query": "name", "counterpart_id": _CHARACTER["id"], "session_id": "conv-x"},
    )
    assert "Jason" in block
    assert "global/global" in block


async def test_turn_retrieval_fail_soft_when_empty():
    cfg = MemoryStepConfig(
        enabled=True, query="{{var.mem_query}}",
        scopes=[{"scope_type": "character", "scope_id": "{{var.counterpart_id}}"}],
    )
    block = await _retrieve_memory_block(
        cfg,
        request=SimpleNamespace(input="anything"),
        text_output="", context="",
        step=SimpleNamespace(name="turn"), step_index=1,
        step_inputs={}, step_outputs={},
        variables={"mem_query": "nothing here xyzzy", "counterpart_id": _CHARACTER["id"]},
    )
    assert block == ""


# ---- write: remember -------------------------------------------------------

def _create_conversation(client):
    r = client.post(BASE + "/conversations", json={
        "title": "Diner", "counterpart_character_id": _CHARACTER["id"],
        "scenario": "1am.", "role_instructions": "Be Mara.",
        "device_user": {"display_name": "You", "persona": "tired"},
        "config": {"enabled_plugins": ["memory", "summarizer"]},
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_remember_action_writes_character_memory(client):
    conv_id = _create_conversation(client)
    r = client.post(
        f"{BASE}/conversations/{conv_id}/plugins/memory/actions/remember",
        json={"text": "I have a dog named Pixel.", "scope": "character", "tags": ["pet"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["scope"] == "character/mara-okafor"
    # Round-trips through the service, and the Markdown file is on disk.
    rec = get_service().read(body["memory_id"])
    assert rec is not None and "Pixel" in rec.body and "pet" in rec.tags
    # The Markdown file landed under the character scope dir (scope_id slugified).
    cfg = get_service().cfg
    files = list((cfg.base_path / "characters").rglob("*.md"))
    assert len(files) == 1


def test_remember_action_session_scope(client):
    conv_id = _create_conversation(client)
    r = client.post(
        f"{BASE}/conversations/{conv_id}/plugins/memory/actions/remember",
        json={"text": "We agreed to meet at the pier.", "scope": "session"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == f"session/{conv_id}"


def test_remember_action_rejects_empty(client):
    conv_id = _create_conversation(client)
    r = client.post(
        f"{BASE}/conversations/{conv_id}/plugins/memory/actions/remember",
        json={"text": "   ", "scope": "character"},
    )
    assert r.status_code == 422, r.text


# ---- write: gist -----------------------------------------------------------

def test_gist_action_writes_distilled_memory(client, monkeypatch):
    conv_id = _create_conversation(client)
    # Commit a user turn so there's a message to gist.
    r = client.post(f"{BASE}/conversations/{conv_id}/turns",
                    json={"items": [{"type": "dialogue", "text": "my dog Pixel chewed my shoe again"}]})
    assert r.status_code == 200, r.text
    user_turn = r.json()["user_turn"]
    item_id = user_turn["items"][0]["id"]

    async def fake_gist_chain(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text("Pixel is the user's dog.", encoding="utf-8")

    monkeypatch.setattr(memory_plugin, "execute_chain_job", fake_gist_chain)
    monkeypatch.setattr(memory_plugin, "_resolve_llm",
                        lambda llm: ChainLLMConfig(api_base="http://x", model="m"))

    r = client.post(
        f"{BASE}/conversations/{conv_id}/plugins/memory/actions/gist",
        json={"turn_id": user_turn["id"], "item_id": item_id, "scope": "character"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gist"] == "Pixel is the user's dog."
    rec = get_service().read(body["memory_id"])
    assert rec is not None and rec.body == "Pixel is the user's dog." and "gist" in rec.tags


# ---- write: summarizer opt-in ---------------------------------------------

def test_summarizer_remember_writes_memory(client, monkeypatch):
    conv_id = _create_conversation(client)
    client.post(f"{BASE}/conversations/{conv_id}/turns",
                json={"items": [{"type": "dialogue", "text": "hi"}]})

    from app.apps.prattletale.plugins.summarizer import plugin as sum_plugin

    async def fake_summary(conversation, character, transcript, *, level, focus=""):
        return "They met at 1am at the diner; Pixel the dog came up."

    monkeypatch.setattr(sum_plugin.summarize, "summarize_history", fake_summary)
    monkeypatch.setattr(sum_plugin, "get_character", lambda cid: dict(_CHARACTER))

    # remember=True writes a memory in addition to the summary turn.
    r = client.post(
        f"{BASE}/conversations/{conv_id}/plugins/summarizer/actions/summarize",
        json={"mode": "keep", "detail": "standard", "remember": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "summary_turn" in body and body.get("memory_id")
    rec = get_service().read(body["memory_id"])
    assert rec is not None and "Pixel" in rec.body

    # remember=False (default) writes nothing extra.
    r2 = client.post(
        f"{BASE}/conversations/{conv_id}/plugins/summarizer/actions/summarize",
        json={"mode": "keep", "detail": "standard"},
    )
    assert r2.status_code == 200, r2.text
    assert "memory_id" not in r2.json()
