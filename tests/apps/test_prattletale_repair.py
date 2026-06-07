"""Deterministic-first repair + the LLM repair fallback."""

from __future__ import annotations

import pytest

from app.apps.prattletale import generator, store
from app.apps.prattletale.repair import repair_output_deterministic

# Reuse the conversation-seeding helpers + the autouse isolation fixture (tmp dirs,
# stubbed default-LLM + counterpart) from the generator tests.
from tests.apps.test_prattletale_generator import (  # noqa: F401 (_isolate is autouse)
    _fake_chain,
    _isolate,
    _seed_conversation,
)


# ---- deterministic pass ----------------------------------------------------

def test_strips_fences_and_emoji():
    raw = "```\n[say] hey there 😀\n[say] what's up 🔥\n```"
    out = repair_output_deterministic(raw)
    assert "```" not in out
    assert "😀" not in out and "🔥" not in out
    assert out == "[say] hey there\n[say] what's up"


def test_drops_empty_lines_and_trims():
    raw = "[say] a\n\n\n[say] b   \n"
    assert repair_output_deterministic(raw) == "[say] a\n[say] b"


def test_strips_leading_assistant_preamble():
    raw = "Sure, here's the reply:\n[say] no\n[say] not happening"
    out = repair_output_deterministic(raw)
    assert "Sure" not in out
    assert out == "[say] no\n[say] not happening"


def test_preamble_strip_never_eats_real_message():
    # A line that looks message-like (tagged/quoted) is never treated as preamble.
    raw = '"here is the thing"\n"okay fine"'
    assert repair_output_deterministic(raw) == '"here is the thing"\n"okay fine"'


def test_caps_runaway_output():
    raw = "\n".join(f"[say] line {i}" for i in range(50))
    out = repair_output_deterministic(raw)
    assert len(out.splitlines()) == 20


def test_never_raises_on_empty():
    assert repair_output_deterministic("") == ""
    assert repair_output_deterministic("   \n  ") == ""


# ---- integration: post-execution repair in run_model_turn ------------------

async def test_clean_reply_parses_without_llm_repair(monkeypatch):
    conv_id = _seed_conversation()
    calls = {"n": 0}

    async def fake(job_id, job_dir, request, event_bus=None):
        calls["n"] += 1
        # director may run first; the turn writes a clean reply.
        text = "[say] clean reply" if request.steps[0].id == "turn" else "{}"
        (job_dir / "final_output.txt").write_text(text, encoding="utf-8")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    turn, _ = await generator.run_model_turn(conv_id)
    assert turn["items"][0]["text"] == "clean reply"
    trace = store.get_trace(conv_id, turn["id"])
    assert trace["repair"] == {"mode": "deterministic", "llm_used": False}


async def test_unparseable_reply_triggers_llm_repair(monkeypatch):
    conv_id = _seed_conversation()

    async def fake(job_id, job_dir, request, event_bus=None):
        sid = request.steps[0].id
        if sid == "turn":
            (job_dir / "final_output.txt").write_text("   \n  ", encoding="utf-8")  # nothing to parse
        elif sid == "repair":
            (job_dir / "final_output.txt").write_text("[say] recovered", encoding="utf-8")
        else:  # director
            (job_dir / "final_output.txt").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    turn, _ = await generator.run_model_turn(conv_id)
    assert turn["items"][0]["text"] == "recovered"
    trace = store.get_trace(conv_id, turn["id"])
    assert trace["repair"]["mode"] == "llm"
    assert trace["repair"]["llm_used"] is True


async def test_repair_disabled_yields_system_error(monkeypatch):
    conv_id = _seed_conversation()
    store.update_conversation(conv_id, {"config": {"repair_enabled": False}})

    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("   \n  "))

    turn, _ = await generator.run_model_turn(conv_id)
    # no LLM repair -> empty parse bubbles up as a system_error turn
    assert turn["items"][0]["type"] == "system_error"
