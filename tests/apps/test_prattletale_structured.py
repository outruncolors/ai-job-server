"""Structured-history turn messages (the default turn path)."""

from __future__ import annotations

from app.apps.prattletale import generator
from app.chain.models import ChainLLMConfig


_CHAR = {"name": "Mara"}


def _ctx(**over):
    base = {
        "character": "CHAR-SHEET",
        "scenario": "SCENARIO",
        "role_instructions": "ROLE",
        "user_persona": "PERSONA",
        "standing_orders": "",
        "voice_feel": "",
        "voice_examples": "",
        "_mem_query": "",
        "_pattern_block": "",
        "_transcript_messages": [],
    }
    base.update(over)
    return base


def test_transcript_to_messages_maps_roles_and_skips():
    turns = [
        {"author": "user", "items": [{"type": "dialogue", "text": "hi"}]},
        {"author": "model", "items": [
            {"type": "dialogue", "text": "hey"},
            {"type": "action", "text": "waves"},
        ]},
        {"author": "system", "items": [{"type": "summary", "text": "they met"}]},
        # skipped: command, ooc, system_error, hidden
        {"author": "user", "items": [{"type": "command", "text": "be brief"}]},
        {"author": "user", "items": [{"type": "ooc", "text": "meta"}]},
        {"author": "model", "items": [{"type": "dialogue", "text": "x", "hidden_from_context": True}]},
    ]
    msgs = generator._transcript_to_messages(turns, _CHAR)
    # Dialogue renders as plain text, other types as parenthesized stage directions
    # (same as _flatten_transcript / _render_item).
    assert msgs == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey (waves)"},
        {"role": "system", "content": "[Earlier] they met"},
    ]


def test_build_structured_messages_ordering():
    tmsgs = [{"role": "user", "content": "hello"}]
    msgs = generator.build_structured_messages(
        _ctx(standing_orders="ORDERS-BLOCK", voice_feel="VOICE-BLOCK"),
        director_block="PLAN FOR THIS REPLY — x",
        transcript_messages=tmsgs,
    )
    roles = [m["role"] for m in msgs]
    blob = [m["content"] for m in msgs]
    # system framing first, then conversation, then orders/memory/plan, then final user.
    assert roles[0] == "system" and "OUTPUT FORMAT" in blob[0]
    assert "CHAR-SHEET" in blob[1] and "SCENARIO" in blob[1]
    assert "VOICE-BLOCK" in blob[2]
    assert {"role": "user", "content": "hello"} in msgs
    # memory message carries the lone {{memory}} token (filled by the executor).
    mem = [m for m in msgs if "{{memory}}" in m["content"]]
    assert len(mem) == 1
    assert "ORDERS-BLOCK" in "\n".join(blob)
    assert "PLAN FOR THIS REPLY" in "\n".join(blob)
    assert msgs[-1]["role"] == "user"  # the final instruction


def test_build_structured_messages_omits_empty_blocks():
    msgs = generator.build_structured_messages(
        _ctx(), director_block="", transcript_messages=[],
    )
    blob = "\n".join(m["content"] for m in msgs)
    # no standing-orders message, no plan message, but memory message always present.
    assert "STANDING ORDERS" not in blob
    assert "PLAN FOR THIS REPLY" not in blob
    assert "{{memory}}" in blob


def test_build_turn_request_structured_puts_messages_not_prompt():
    ctx = _ctx(_transcript_messages=[{"role": "user", "content": "yo"}])
    req = generator.build_turn_request(
        ctx, ChainLLMConfig(api_base="http://x", model="m"),
        structured_chat_history=True, counterpart_id="mara")
    alt = req.steps[0].alternatives[0]
    assert alt.prompt == ""
    assert alt.messages is not None
    assert {"role": "user", "content": "yo"} in alt.messages
    assert alt.memory is not None  # memory config still attached


def test_build_turn_request_single_prompt_when_disabled():
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"),
        structured_chat_history=False, counterpart_id="mara")
    alt = req.steps[0].alternatives[0]
    assert alt.messages is None
    assert alt.prompt  # single rendered prompt
