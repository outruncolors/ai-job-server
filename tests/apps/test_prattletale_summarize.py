"""SP2 — the map-reduce summarization engine + summary rendering.

The chain executor is stubbed (no GPU): the fake writes a deterministic
``final_output.txt`` derived from the rendered prompt and records every call so we
can assert chunking, the reduce fan-in, and that the detail level + focus reach the
prompt. Prompt Pal points at an empty tmp dir, so resolution uses the in-code
``summarize.*`` defaults.
"""

from __future__ import annotations

import pytest

from app.apps.prattletale import generator
from app.apps.prattletale.models import Author, ItemType
from app.apps.prattletale.plugins.summarizer import summarize
from app.chain.models import ChainLLMConfig
from app.prompt_pal import store as pp_store

_CHARACTER = {"id": "mara-okafor", "name": "Mara"}
_LLM = ChainLLMConfig(api_base="http://x", model="m")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")


class _Recorder:
    def __init__(self):
        self.calls: list[dict] = []

    def fake(self):
        async def _fake(job_id, job_dir, request, event_bus=None):
            prompt = request.input
            title = request.title
            self.calls.append({"title": title, "prompt": prompt})
            n = len([c for c in self.calls if c["title"] == title])
            out = f"[{title} #{n}] " + ("merged" if title == "Reduce summaries" else "partial")
            (job_dir / "final_output.txt").write_text(out, encoding="utf-8")
        return _fake


def _user_turn(seq: int, text: str) -> dict:
    tid = f"t{seq:04d}"
    return {
        "id": tid, "author": Author.user.value, "created_at": "x",
        "items": [{"id": f"{tid}-i01", "turn_id": tid, "author": Author.user.value,
                   "type": ItemType.dialogue.value, "text": text, "hidden_from_context": False}],
    }


def _transcript(n: int) -> dict:
    return {"conversation_id": "c", "turns": [_user_turn(i, f"line {i}") for i in range(1, n + 1)],
            "next_turn_seq": n + 1}


# --- reduce / chunk counting -----------------------------------------------

async def test_long_history_reduces_to_one_string(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(summarize, "execute_chain_job", rec.fake())
    out = await summarize.summarize_history(
        {}, _CHARACTER, _transcript(6), level="standard",
        chunk_turns=2, reduce_fanin=2, llm=_LLM,
    )
    assert isinstance(out, str) and out
    # 6 turns / chunk 2 = 3 chunks -> 3 map calls.
    maps = [c for c in rec.calls if c["title"] == "Summarize chunk"]
    reduces = [c for c in rec.calls if c["title"] == "Reduce summaries"]
    assert len(maps) == 3
    # 3 partials, fanin 2: round1 [2]->1 reduce + singleton passes through (2 partials);
    # round2 [2]->1 reduce. Total 2 reduce calls.
    assert len(reduces) == 2


async def test_single_chunk_skips_reduce(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(summarize, "execute_chain_job", rec.fake())
    out = await summarize.summarize_history(
        {}, _CHARACTER, _transcript(3), level="brief",
        chunk_turns=10, reduce_fanin=4, llm=_LLM,
    )
    assert out == "[Summarize chunk #1] partial"
    assert [c["title"] for c in rec.calls] == ["Summarize chunk"]


async def test_empty_history_returns_empty(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(summarize, "execute_chain_job", rec.fake())
    out = await summarize.summarize_history(
        {}, _CHARACTER, _transcript(0), level="standard", llm=_LLM,
    )
    assert out == ""
    assert rec.calls == []


# --- detail level + focus reach the prompt ---------------------------------

async def test_detail_level_and_focus_reach_prompt(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(summarize, "execute_chain_job", rec.fake())
    await summarize.summarize_history(
        {}, _CHARACTER, _transcript(2), level="detailed", focus="the missing key",
        chunk_turns=10, llm=_LLM,
    )
    prompt = rec.calls[0]["prompt"]
    # the 'detailed' level directive text is composed into {{var.detail}}
    assert "Be thorough" in prompt
    # the focus note is appended as a trailing directive
    assert "the missing key" in prompt
    # the transcript chunk is rendered into the prompt
    assert "line 1" in prompt and "line 2" in prompt


async def test_bad_level_raises_value_error(monkeypatch):
    monkeypatch.setattr(summarize, "execute_chain_job", _Recorder().fake())
    with pytest.raises(ValueError):
        await summarize.summarize_history({}, _CHARACTER, _transcript(2), level="nope", llm=_LLM)


# --- covered-turn gathering (hidden / error skipped) ------------------------

async def test_covered_turns_skip_hidden_and_error(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(summarize, "execute_chain_job", rec.fake())
    transcript = _transcript(2)
    # Hide turn 1's only item; add an error turn — neither should be covered.
    transcript["turns"][0]["items"][0]["hidden_from_context"] = True
    transcript["turns"].append({
        "id": "t0003", "author": Author.model.value, "created_at": "x",
        "items": [{"id": "t0003-i01", "turn_id": "t0003", "author": Author.model.value,
                   "type": ItemType.system_error.value, "text": "boom", "hidden_from_context": False}],
    })
    await summarize.summarize_history({}, _CHARACTER, transcript, level="brief",
                                      chunk_turns=10, llm=_LLM)
    # Only turn 2 ("line 2") is covered.
    prompt = rec.calls[0]["prompt"]
    assert "line 2" in prompt
    assert "line 1" not in prompt
    assert "boom" not in prompt


# --- summary rendering in build_context ------------------------------------

def test_flatten_renders_summary_as_summary_so_far():
    turns = [
        {"id": "t0001", "author": Author.system.value, "created_at": "x",
         "items": [{"type": ItemType.summary.value, "text": "They argued about the key.",
                    "hidden_from_context": False}]},
        {"id": "t0002", "author": Author.user.value, "created_at": "x",
         "items": [{"type": ItemType.dialogue.value, "text": "so where is it",
                    "hidden_from_context": False}]},
    ]
    flat = generator._flatten_transcript(turns, _CHARACTER)
    assert "[Summary so far] They argued about the key." in flat
    assert "[User] so where is it" in flat
    # the summary turn is not dropped
    assert flat.splitlines()[0].startswith("[Summary so far]")
