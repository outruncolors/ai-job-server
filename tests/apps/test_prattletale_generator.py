"""SP3 — generator pipeline. The chain executor is mocked (no GPU node)."""

from __future__ import annotations

import json

import pytest

from app import wildcards
from app.apps.prattletale import generator, store
from app.chain.models import ChainLLMConfig
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Conversations under tmp; default LLM + counterpart stubbed. Prompt Pal +
    wildcard stores point at empty tmp dirs so resolution uses the in-code
    defaults and never touches the real config."""
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")
    monkeypatch.setattr(wildcards, "_DIR", tmp_path / "wildcards")
    monkeypatch.setattr(wildcards, "_INDEX_PATH", tmp_path / "wildcards" / "index.json")
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
    # User dialogue is stored/flattened in canonical (double-quoted) form.
    assert '[User] "you actually showed up"' in trace["context_input"]["transcript"]


# ---- director (per-turn JSON plan) -----------------------------------------

async def test_director_plan_injected_into_the_turn_prompt(monkeypatch):
    conv_id = _seed_conversation()  # director_enabled defaults on
    store.append_user_turn(conv_id, [{"type": "dialogue", "text": "you came back"}])

    captured = {}

    async def fake(job_id, job_dir, request, event_bus=None):
        if request.steps[0].id == "director":
            (job_dir / "final_output.txt").write_text(
                '{"reply_shape": {"message_count": 1}, "conversation_move": "DIRECTOR-MOVE",'
                ' "emotional_temperature": "DIRECTOR-SHADE", "length": "terse"}',
                encoding="utf-8")
        else:  # the turn job — capture the structured turn-step messages
            alt = request.steps[0].alternatives[0]
            captured["turn_blob"] = "\n".join(m["content"] for m in (alt.messages or []))
            (job_dir / "final_output.txt").write_text('[say] hey', encoding="utf-8")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    turn, _ = await generator.run_model_turn(conv_id)
    assert turn["items"][0]["text"] == "hey"
    # the director's chosen plan (not a wildcard draw) reached the turn messages
    assert "DIRECTOR-SHADE" in captured["turn_blob"]
    assert "DIRECTOR-MOVE" in captured["turn_blob"]


async def test_director_failure_falls_back_without_sinking_the_reply(monkeypatch):
    conv_id = _seed_conversation()
    store.append_user_turn(conv_id, [{"type": "dialogue", "text": "hi"}])

    async def fake(job_id, job_dir, request, event_bus=None):
        if request.steps[0].id == "director":
            raise RuntimeError("director LLM exploded")
        (job_dir / "final_output.txt").write_text('[say] still here', encoding="utf-8")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    turn, _ = await generator.run_model_turn(conv_id)
    # director blew up but the reply still committed (wildcard fallback / no plan)
    assert turn["items"][0]["text"] == "still here"
    assert turn["items"][0]["status"] == "committed"


async def test_director_garbage_output_falls_back(monkeypatch):
    conv_id = _seed_conversation()
    store.append_user_turn(conv_id, [{"type": "dialogue", "text": "hi"}])

    async def fake(job_id, job_dir, request, event_bus=None):
        if request.steps[0].id == "director":
            (job_dir / "final_output.txt").write_text("not json at all", encoding="utf-8")
        else:
            (job_dir / "final_output.txt").write_text('[say] ok', encoding="utf-8")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    turn, _ = await generator.run_model_turn(conv_id)
    assert turn["items"][0]["text"] == "ok"
    assert turn["items"][0]["status"] == "committed"


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


# ---- regenerate (versions) -------------------------------------------------

async def test_regenerate_appends_a_version_and_excludes_the_turn_from_context(monkeypatch):
    conv_id = _seed_conversation()
    store.append_user_turn(conv_id, [{"type": "dialogue", "text": "hi"}])
    base = store.append_model_turn(conv_id, [{"type": "dialogue", "text": "original"}], job_id="j0")

    captured = {}

    async def fake(job_id, job_dir, request, event_bus=None):
        captured["input"] = request.input  # the flattened transcript fed to the prompt
        (job_dir / "final_output.txt").write_text("[say] a fresh take.", encoding="utf-8")

    monkeypatch.setattr(generator, "execute_chain_job", fake)

    turn, _ = await generator.run_model_turn(conv_id, add_version_turn_id=base["id"])
    assert len(turn["versions"]) == 2
    assert turn["active_version"] == 1
    assert turn["versions"][0]["items"][0]["text"] == "original"
    assert turn["items"][0]["text"] == "a fresh take."
    # the turn being regenerated is excluded from its own context
    assert "original" not in captured["input"]


async def test_failed_regenerate_reraises_and_leaves_turn_intact(monkeypatch):
    conv_id = _seed_conversation()
    base = store.append_model_turn(conv_id, [{"type": "dialogue", "text": "keep me"}], job_id="j0")
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("   \n  "))  # empty parse -> error

    with pytest.raises(generator.GenerationError):
        await generator.run_model_turn(conv_id, add_version_turn_id=base["id"])

    # no system_error turn appended; the original turn stands, still unversioned
    turns = store.get_transcript(conv_id)["turns"]
    assert [t["id"] for t in turns] == [base["id"]]
    assert turns[0]["items"][0]["text"] == "keep me"
    assert turns[0].get("versions") is None


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


def test_build_turn_request_has_no_variety_or_guard_step():
    # Both the variety pass (now empty default) and the guard step are retired:
    # the turn step stands alone even with the variety flag on.
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"), variety=True)
    assert [s.id for s in req.steps] == ["turn"]
    assert [s.number for s in req.steps] == [1]


def test_whole_turn_pipeline_runs_without_thinking():
    # Reasoning is disabled across the chat-turn pipeline: it degrades the reply
    # and on variety/guard can exhaust max_tokens (empty content -> "no items").
    req = generator.build_turn_request(_ctx(), ChainLLMConfig(api_base="http://x", model="m"))
    assert all(s.primary.thinking is False for s in req.steps)


def test_resolve_llm_raises_max_tokens_floor():
    low = ChainLLMConfig(api_base="http://x", model="m", max_tokens=2048)
    assert generator._resolve_llm(low).max_tokens == generator._MIN_TURN_MAX_TOKENS
    # Never lowers an already-larger budget.
    high = ChainLLMConfig(api_base="http://x", model="m", max_tokens=20000)
    assert generator._resolve_llm(high).max_tokens == 20000
