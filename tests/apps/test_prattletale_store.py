"""SP1 store tests — file-per-conversation persistence (no LLM, no network)."""

from __future__ import annotations

import json

import pytest

from app.apps.prattletale import store


@pytest.fixture(autouse=True)
def _tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")


def _make_conversation(**overrides) -> dict:
    fields = {
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "It's 1am at an all-night diner. Rain outside.",
        "role_instructions": "Stay in character as Mara.",
        "device_user": {"display_name": "You", "persona": "A regular."},
    }
    fields.update(overrides)
    return store.create_conversation(fields)


def test_create_writes_both_files_with_slug_id():
    conv = _make_conversation()
    assert conv["id"] == "late_night_diner"
    conv_dir = store.CONVERSATIONS_DIR / conv["id"]
    assert (conv_dir / "conversation.json").exists()
    assert (conv_dir / "transcript.json").exists()

    transcript = json.loads((conv_dir / "transcript.json").read_text())
    assert transcript["conversation_id"] == conv["id"]
    assert transcript["turns"] == []
    assert transcript["next_turn_seq"] == 1

    # round-trips through get_*
    assert store.get_conversation(conv["id"])["title"] == "Late-night diner"
    assert store.get_transcript(conv["id"])["turns"] == []


def test_create_slug_id_unique_against_existing_folders():
    a = _make_conversation()
    b = _make_conversation()
    assert a["id"] == "late_night_diner"
    assert b["id"] == "late_night_diner_2"


def test_append_user_then_model_turns_assign_monotonic_ids_and_round_trip():
    conv = _make_conversation()
    cid = conv["id"]

    user_turn = store.append_user_turn(cid, [{"type": "dialogue", "text": "you actually showed up"}])
    assert user_turn["id"] == "t0001"
    assert user_turn["author"] == "user"
    assert user_turn["items"][0]["id"] == "t0001-i01"
    assert user_turn["items"][0]["turn_id"] == "t0001"
    assert user_turn["items"][0]["status"] == "committed"
    assert user_turn["items"][0]["hidden_from_context"] is False
    assert user_turn["items"][0]["audio"] is None

    model_turn = store.append_model_turn(
        cid,
        [
            {"type": "narration_emotion", "text": "She doesn't look up."},
            {"type": "dialogue", "text": "Where else would I be."},
        ],
        job_id="job_abc",
    )
    assert model_turn["id"] == "t0002"
    assert model_turn["author"] == "model"
    assert model_turn["job_id"] == "job_abc"
    assert [it["id"] for it in model_turn["items"]] == ["t0002-i01", "t0002-i02"]

    transcript = store.get_transcript(cid)
    assert [t["id"] for t in transcript["turns"]] == ["t0001", "t0002"]
    assert transcript["next_turn_seq"] == 3


def test_replace_turn_overwrites_in_place():
    conv = _make_conversation()
    cid = conv["id"]
    store.append_user_turn(cid, [{"type": "dialogue", "text": "hi"}])
    err = store.append_error_turn(cid, "LLM exploded", job_id="job_1")

    replaced = store.replace_turn(
        cid,
        err["id"],
        [{"type": "dialogue", "text": "recovered reply"}],
        author="model",
        job_id="job_2",
    )
    assert replaced["id"] == err["id"]  # same turn id
    assert replaced["items"][0]["text"] == "recovered reply"
    assert replaced["items"][0]["status"] == "committed"
    assert replaced["job_id"] == "job_2"

    transcript = store.get_transcript(cid)
    # still two turns, order preserved, no duplicate
    assert [t["id"] for t in transcript["turns"]] == ["t0001", "t0002"]
    assert transcript["turns"][1]["items"][0]["text"] == "recovered reply"
    assert transcript["next_turn_seq"] == 3


def test_append_error_turn_yields_one_system_error_item():
    conv = _make_conversation()
    cid = conv["id"]
    err = store.append_error_turn(cid, "boom", job_id="job_x")
    assert err["author"] == "model"
    assert err["job_id"] == "job_x"
    assert len(err["items"]) == 1
    item = err["items"][0]
    assert item["type"] == "system_error"
    assert item["status"] == "error"
    assert item["text"] == "boom"


def test_replace_turn_missing_returns_none():
    conv = _make_conversation()
    assert store.replace_turn(conv["id"], "t9999", [{"type": "dialogue", "text": "x"}]) is None


def test_user_items_stored_in_canonical_format():
    conv = _make_conversation()
    cid = conv["id"]
    turn = store.append_user_turn(cid, [
        {"type": "dialogue", "text": "hello"},
        {"type": "action", "text": "turns around"},
        {"type": "narration", "text": "The room goes quiet."},
    ])
    texts = [it["text"] for it in turn["items"]]
    assert texts == ['"hello"', "*turns around*", "The room goes quiet."]


def test_user_items_are_not_double_wrapped():
    conv = _make_conversation()
    cid = conv["id"]
    turn = store.append_user_turn(cid, [
        {"type": "dialogue", "text": '"hello"'},
        {"type": "action", "text": "*turns around*"},
    ])
    texts = [it["text"] for it in turn["items"]]
    assert texts == ['"hello"', "*turns around*"]


def test_model_items_are_stored_verbatim():
    # The model already emits canonical text (parsed upstream); the store must not
    # re-wrap it the way it canonicalizes user-composed bubbles.
    conv = _make_conversation()
    cid = conv["id"]
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "hello"}], job_id="j")
    assert turn["items"][0]["text"] == "hello"


def test_transcript_ops_on_missing_conversation_return_none():
    assert store.get_transcript("nope") is None
    assert store.append_user_turn("nope", [{"type": "dialogue", "text": "x"}]) is None


def test_write_trace_persists_under_traces_dir():
    conv = _make_conversation()
    cid = conv["id"]
    turn = store.append_model_turn(cid, [{"type": "dialogue", "text": "hi"}], job_id="j")
    store.write_trace(cid, turn["id"], {"job_id": "j", "raw_final_output": "[say] hi"})
    trace_path = store.CONVERSATIONS_DIR / cid / "traces" / f"{turn['id']}.json"
    assert json.loads(trace_path.read_text())["raw_final_output"] == "[say] hi"


def test_list_conversations_summaries_with_last_item_preview():
    conv = _make_conversation()
    store.append_user_turn(conv["id"], [{"type": "dialogue", "text": "first"}])
    store.append_model_turn(conv["id"], [{"type": "dialogue", "text": "last bubble"}], job_id="j")

    summaries = store.list_conversations()
    assert len(summaries) == 1
    s = summaries[0]
    assert s["id"] == conv["id"]
    assert s["title"] == "Late-night diner"
    assert s["counterpart_character_id"] == "mara-okafor"
    assert s["last_item_preview"] == "last bubble"


def test_delete_conversation_removes_folder():
    conv = _make_conversation()
    cid = conv["id"]
    assert (store.CONVERSATIONS_DIR / cid).exists()
    assert store.delete_conversation(cid) is True
    assert not (store.CONVERSATIONS_DIR / cid).exists()
    assert store.delete_conversation(cid) is False
