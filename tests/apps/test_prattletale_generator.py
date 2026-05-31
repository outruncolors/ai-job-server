"""SP3 — generator pipeline. The chain executor is mocked (no GPU node)."""

from __future__ import annotations

import json

import pytest

from app.apps.prattletale import generator, store
from app.chain.models import ChainLLMConfig
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Conversations under tmp; default LLM + counterpart stubbed. Prompt Pal store
    points at an empty tmp dir so prompt resolution uses the in-code defaults."""
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))


def _seed_conversation() -> str:
    conv = store.create_conversation({
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
        "role_instructions": "Stay in character as Mara.",
        "device_user": {"display_name": "You", "persona": "A regular, tired but curious."},
    })
    return conv["id"]


def _fake_chain(output: str):
    """A fake execute_chain_job that writes a fixed `final_output.txt`."""
    async def fake(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(output, encoding="utf-8")
    return fake


# ---- happy path ------------------------------------------------------------

async def test_run_model_turn_commits_a_typed_turn_and_trace(monkeypatch):
    conv_id = _seed_conversation()
    store.append_user_turn(conv_id, [{"type": "dialogue", "text": "you actually showed up"}])

    output = "[narration] She doesn't look up from the menu.\n[say] Where else would I be."
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain(output))

    turn, job_id = await generator.run_model_turn(conv_id)

    assert job_id
    assert turn["author"] == "model"
    assert [i["type"] for i in turn["items"]] == ["narration", "dialogue"]
    assert turn["items"][1]["text"] == "Where else would I be."
    assert all(i["status"] == "committed" for i in turn["items"])

    # the turn round-trips on disk
    transcript = store.get_transcript(conv_id)
    assert transcript["turns"][-1]["id"] == turn["id"]

    # trace captured the run
    trace = json.loads(
        (store._trace_path(conv_id, turn["id"])).read_text(encoding="utf-8")
    )
    assert trace["job_id"] == job_id
    assert trace["raw_final_output"] == output
    assert trace["error"] is None
    assert len(trace["parsed_items"]) == 2
    assert "[User] you actually showed up" in trace["context_input"]["transcript"]


# ---- failure path ----------------------------------------------------------

async def test_empty_output_yields_a_system_error_turn(monkeypatch):
    conv_id = _seed_conversation()
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("   \n  "))

    # must not raise to the caller
    turn, job_id = await generator.run_model_turn(conv_id)

    assert turn["author"] == "model"
    assert len(turn["items"]) == 1
    assert turn["items"][0]["type"] == "system_error"
    assert turn["items"][0]["status"] == "error"

    # the error turn is persisted as the latest turn
    assert store.get_transcript(conv_id)["turns"][-1]["items"][0]["type"] == "system_error"


async def test_missing_counterpart_yields_a_system_error_turn(monkeypatch):
    conv_id = _seed_conversation()
    monkeypatch.setattr(generator, "get_character", lambda cid: None)
    # executor should never be reached
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("[say] hi"))

    turn, _ = await generator.run_model_turn(conv_id)
    assert turn["items"][0]["type"] == "system_error"


async def test_missing_conversation_raises():
    with pytest.raises(generator.GenerationError):
        await generator.run_model_turn("does-not-exist")


# ---- build_context (pure) --------------------------------------------------

def test_build_context_excludes_hidden_and_error_items():
    transcript = {
        "turns": [
            {"id": "t0001", "author": "user", "items": [
                {"type": "dialogue", "text": "visible", "hidden_from_context": False},
                {"type": "dialogue", "text": "secret", "hidden_from_context": True},
            ]},
            {"id": "t0002", "author": "model", "items": [
                {"type": "system_error", "text": "boom"},
            ]},
            {"id": "t0003", "author": "model", "items": [
                {"type": "narration", "text": "she sighs"},
                {"type": "dialogue", "text": "fine"},
            ]},
        ],
    }
    conversation = {"scenario": "s", "role_instructions": "r", "config": {}}
    ctx = generator.build_context(conversation, _CHARACTER, transcript)

    lines = ctx["transcript"].splitlines()
    # hidden item dropped; the error-only turn produces no line at all
    assert lines == ["[User] visible", "[Mara] (she sighs) fine"]
    assert "secret" not in ctx["transcript"]
    assert "boom" not in ctx["transcript"]


def test_build_context_renders_empty_persona_cleanly():
    transcript = {"turns": []}
    conversation = {"device_user": {"persona": ""}, "config": {}}
    ctx = generator.build_context(conversation, _CHARACTER, transcript)
    assert ctx["user_persona"] == generator._EMPTY_PERSONA
    assert ctx["user_persona"].strip()  # never blank → no dangling label


def test_build_context_windows_to_recent_turns():
    turns = [
        {"id": f"t{n:04d}", "author": "user", "items": [{"type": "dialogue", "text": str(n)}]}
        for n in range(1, 6)
    ]
    conversation = {"config": {"context_window_turns": 2}}
    ctx = generator.build_context(conversation, _CHARACTER, {"turns": turns})
    assert ctx["transcript"].splitlines() == ["[User] 4", "[User] 5"]


# ---- chain shape: variety pass ---------------------------------------------

def _ctx() -> dict:
    return {"character": "c", "scenario": "s", "role_instructions": "r",
            "user_persona": "p", "transcript": "[User] hi"}


def test_build_turn_request_includes_variety_step_by_default():
    req = generator.build_turn_request(_ctx(), ChainLLMConfig(api_base="http://x", model="m"))
    assert [s.id for s in req.steps] == ["turn", "variety", "guard"]


def test_build_turn_request_skips_variety_when_disabled():
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"), variety=False
    )
    assert [s.id for s in req.steps] == ["turn", "guard"]
    assert [s.number for s in req.steps] == [1, 2]  # numbering stays contiguous
