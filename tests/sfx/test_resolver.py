"""app.sfx.resolver — eligibility, chance-before-LLM, chooser/guard, persistence."""

from __future__ import annotations

import json
import random

import pytest

import app.sfx.prompts  # noqa: F401 — registers sfx.choose_emote so get_text/get_guard resolve
from app.chain.models import ChainLLMConfig
from app.sfx import resolver

_LLM = ChainLLMConfig(api_base="http://fake", model="fake")


def _fake_chain(chooser: dict, guard: dict | None):
    """Return an async stand-in for execute_chain_job that writes the step + final
    outputs the resolver reads (steps/*_choose/output.txt and final_output.txt)."""
    async def run(job_id, job_dir, request, event_bus=None):
        step_dir = job_dir / "steps" / "001_choose"
        step_dir.mkdir(parents=True, exist_ok=True)
        step_dir.joinpath("output.txt").write_text(json.dumps(chooser), encoding="utf-8")
        final = json.dumps(guard) if guard is not None else json.dumps(chooser)
        (job_dir / "final_output.txt").write_text(final, encoding="utf-8")
    return run


async def test_ineligible_type_skips(sfx_root):
    desc, _ = await resolver.resolve_sfx(item_type="dialogue", item_text="hi", llm=_LLM)
    assert desc["status"] == "skipped" and desc["reason"] == "ineligible_type"


async def test_chance_roll_skips_before_llm(sfx_root, monkeypatch):
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
    monkeypatch.setattr(resolver, "execute_chain_job", boom)

    desc, trace = await resolver.resolve_sfx(
        item_type="action", item_text="she sneezes", identity="young_woman",
        chance=0.0, llm=_LLM, rng=random.Random(1))
    assert desc["status"] == "skipped" and desc["reason"] == "chance_roll"
    assert called["n"] == 0  # the LLM chain never ran


async def test_empty_catalog_short_circuits(sfx_root, monkeypatch):
    called = {"n": 0}

    async def boom(*a, **k):
        called["n"] += 1
    monkeypatch.setattr(resolver, "execute_chain_job", boom)

    desc, _ = await resolver.resolve_sfx(item_type="action", item_text="x", force=True, llm=_LLM)
    assert desc["status"] == "none" and desc["reason"] == "empty_catalog"
    assert called["n"] == 0


async def test_resolved_picks_variant_in_category(sfx_root, monkeypatch):
    monkeypatch.setattr(resolver, "execute_chain_job", _fake_chain(
        {"decision": "choose", "category": "sneeze", "effect_id": None,
         "confidence": 0.9, "reason": "she sneezes"},
        {"decision": "keep", "reason": "explicit sneeze"}))

    desc, trace = await resolver.resolve_sfx(
        item_type="action", item_text="she sneezes", identity="young_woman",
        force=True, llm=_LLM, rng=random.Random(0))
    assert desc["status"] == "resolved"
    assert desc["selection"]["category"] == "sneeze"
    assert desc["effect_id"].startswith("yw_sneeze")
    assert desc["url"].startswith("/v1/sfx/file/")
    assert trace["result"]["status"] == "resolved"


async def test_guard_rejects(sfx_root, monkeypatch):
    monkeypatch.setattr(resolver, "execute_chain_job", _fake_chain(
        {"decision": "choose", "category": "laugh", "confidence": 0.4, "reason": "maybe"},
        {"decision": "reject", "reason": "contrived"}))
    desc, _ = await resolver.resolve_sfx(
        item_type="narration", item_text="the room is quiet", identity="young_woman",
        force=True, llm=_LLM)
    assert desc["status"] == "rejected"
    assert desc["candidate"]["category"] == "laugh"


async def test_chooser_none(sfx_root, monkeypatch):
    monkeypatch.setattr(resolver, "execute_chain_job", _fake_chain(
        {"decision": "none", "category": None, "reason": "no clear sound"},
        {"decision": "keep", "reason": "ok"}))
    desc, _ = await resolver.resolve_sfx(
        item_type="action", item_text="she thinks about lunch", identity="young_woman",
        force=True, llm=_LLM)
    assert desc["status"] == "none"


async def test_resolver_error_is_captured(sfx_root, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("llm down")
    monkeypatch.setattr(resolver, "execute_chain_job", boom)
    desc, _ = await resolver.resolve_sfx(
        item_type="action", item_text="she sneezes", identity="young_woman",
        force=True, llm=_LLM)
    assert desc["status"] == "error" and desc["reason"] == "resolver_failed"
