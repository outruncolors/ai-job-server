"""SP7 — edge cases across the store, the parser, and ``build_context``.

These cover the failure-adjacent corners the happy-path sub-phase tests don't:
the empty-transcript first turn, oversized / overlong context windows, the
parser invariant the format-hygiene guard relies on (leaked meta / OOC never
inflates the bubble count), concurrent appends to one conversation (the store
re-reads before writing), and an entirely absent ``device_user``.
"""

from __future__ import annotations

import pytest

from app.apps.prattletale import generator, store
from app.apps.prattletale.prompts import parse_items
from app.chain.models import ChainLLMConfig

_CHARACTER = {"id": "mara-okafor", "name": "Mara", "summary": "a tired diner regular"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))


def _fake_chain(output: str):
    async def fake(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(output, encoding="utf-8")
    return fake


def _seed() -> str:
    return store.create_conversation({
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
        "role_instructions": "Stay in character as Mara.",
        "device_user": {"display_name": "You", "persona": "A regular."},
    })["id"]


# ---- empty-transcript first turn -------------------------------------------

def test_build_context_on_empty_transcript_is_clean():
    """No prior turns -> an empty (not malformed) transcript string and a
    rendered persona, so the very first reply has a valid prompt."""
    conversation = {"scenario": "s", "role_instructions": "r",
                    "device_user": {"persona": "p"}, "config": {}}
    ctx = generator.build_context(conversation, _CHARACTER, {"turns": []})
    assert ctx["transcript"] == ""
    assert ctx["user_persona"] == "p"
    assert ctx["character"]  # the counterpart sheet still renders


async def test_first_turn_against_empty_transcript_commits(monkeypatch):
    """A model turn with zero prior turns (the user's first message) succeeds."""
    conv_id = _seed()
    store.append_user_turn(conv_id, [{"type": "dialogue", "text": "hi?"}])
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain("[say] hey, you"))

    turn, job_id = await generator.run_model_turn(conv_id)
    assert job_id
    assert turn["author"] == "model"
    assert [i["type"] for i in turn["items"]] == ["dialogue"]


# ---- oversized / overlong context window -----------------------------------

def test_window_larger_than_history_keeps_all_turns():
    turns = [
        {"id": f"t{n:04d}", "author": "user", "items": [{"type": "dialogue", "text": str(n)}]}
        for n in range(1, 4)
    ]
    conversation = {"config": {"context_window_turns": 100}}  # more than exist
    ctx = generator.build_context(conversation, _CHARACTER, {"turns": turns})
    assert ctx["transcript"].splitlines() == ["[User] 1", "[User] 2", "[User] 3"]


def test_very_long_turn_text_is_preserved_verbatim():
    long_text = "x" * 20_000
    turns = [{"id": "t0001", "author": "user",
              "items": [{"type": "dialogue", "text": long_text}]}]
    conversation = {"config": {"context_window_turns": 12}}
    ctx = generator.build_context(conversation, _CHARACTER, {"turns": turns})
    assert ctx["transcript"] == f"[User] {long_text}"


def test_zero_or_negative_window_falls_back_to_full_history():
    turns = [
        {"id": f"t{n:04d}", "author": "user", "items": [{"type": "dialogue", "text": str(n)}]}
        for n in range(1, 4)
    ]
    for window in (0, -1):
        ctx = generator.build_context(
            {"config": {"context_window_turns": window}}, _CHARACTER, {"turns": turns}
        )
        assert ctx["transcript"].splitlines() == ["[User] 1", "[User] 2", "[User] 3"]


# ---- parser contract: one message per line ---------------------------------
# The guard itself is an LLM pass (untestable here); these pin the parser
# contract it leans on — one canonical line == one item, and any meta / OOC the
# guard fails to strip degrades to a plain narration bubble (never throws).

def test_line_count_equals_bubble_count():
    raw = "\n".join([
        "She doesn't look up.",
        '"Where else would I be."',
        "*She slides the menu over.*",
        "_more relieved than she'll admit_",
    ])
    items = parse_items(raw)
    assert len(items) == 4  # four lines -> exactly four bubbles
    # narration / dialogue / action / (underscore-wrapped -> narration)
    assert [i["type"] for i in items] == [
        "narration", "dialogue", "action", "narration",
    ]


def test_leaked_meta_line_becomes_its_own_narration_bubble():
    """An OOC / meta line the guard missed is undecorated, so it parses as a
    plain narration bubble (the guard is what strips OOC upstream)."""
    raw = '"hey"\n(OOC: let me know if this is too much)\n"you came back"'
    items = parse_items(raw)
    assert [i["type"] for i in items] == ["dialogue", "narration", "dialogue"]
    assert items[0]["text"] == "hey"
    assert items[1]["text"] == "(OOC: let me know if this is too much)"
    assert items[2]["text"] == "you came back"


# ---- concurrent-write safety: appends re-read before writing ----------------

def test_concurrent_append_does_not_clobber_an_interleaved_write():
    """Regression: ``_append_turn`` re-reads ``transcript.json`` immediately
    before writing, so a turn written by another worker between two store calls
    survives. Simulate the interleaving by writing a turn straight to disk
    (behind the store's back) and confirm the next store append preserves it."""
    conv_id = _seed()
    store.append_user_turn(conv_id, [{"type": "dialogue", "text": "one"}])  # t0001

    # Another worker appends t0002 directly on disk and bumps next_turn_seq.
    transcript = store._read_transcript(conv_id)
    transcript["turns"].append({
        "id": "t0002", "author": "user", "created_at": "2026-01-01T00:00:00Z",
        "job_id": None,
        "items": [{"id": "t0002-i01", "turn_id": "t0002", "author": "user",
                   "type": "dialogue", "text": "two", "status": "committed",
                   "audio": None, "hidden_from_context": False,
                   "created_at": "2026-01-01T00:00:00Z"}],
    })
    transcript["next_turn_seq"] = 3
    store._atomic_write(store._transcript_path(conv_id), transcript)

    # The store append must read the fresh file -> t0003, with t0002 intact.
    third = store.append_model_turn(conv_id, [{"type": "dialogue", "text": "three"}])
    assert third["id"] == "t0003"

    persisted = store.get_transcript(conv_id)
    assert [t["id"] for t in persisted["turns"]] == ["t0001", "t0002", "t0003"]
    assert persisted["next_turn_seq"] == 4
    # the interleaved turn was not lost
    assert persisted["turns"][1]["items"][0]["text"] == "two"


# ---- empty / absent device_user --------------------------------------------

def test_build_context_with_no_device_user_key_renders_placeholder():
    ctx = generator.build_context({"config": {}}, _CHARACTER, {"turns": []})
    assert ctx["user_persona"] == generator._EMPTY_PERSONA
    assert ctx["user_persona"].strip()


def test_build_context_with_whitespace_persona_renders_placeholder():
    conversation = {"device_user": {"persona": "   \n  "}, "config": {}}
    ctx = generator.build_context(conversation, _CHARACTER, {"turns": []})
    assert ctx["user_persona"] == generator._EMPTY_PERSONA
