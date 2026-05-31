"""SP6 — voice synthesis + degrade-to-text. The chain executor and the TTS
boundary (``voice._synth_to_wav``) are stubbed; the ``voice`` capability is
monkeypatched (no GPU/OmniVoice needed)."""

from __future__ import annotations

import json
import wave

import pytest

from app.apps.prattletale import generator, settings_store, store, voice
from app.chain.models import ChainLLMConfig

_CP_VOICE = "cp-voice-1"
_NARRATOR_VOICE = "narrator-voice-1"
_CHARACTER = {
    "id": "mara-okafor",
    "name": "Mara",
    "summary": "a tired diner regular",
    "speaking_style": {"voice_preset_id": _CP_VOICE},
}

# one model turn with a spoken line, a narration beat, and a (silent) action
_OUTPUT = "[say] you came back\n[narration] she sets down the mug\n[do] slides the menu over"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )
    monkeypatch.setattr(generator, "get_character", lambda cid: dict(_CHARACTER))
    monkeypatch.setattr(generator, "execute_chain_job", _fake_chain(_OUTPUT))


def _fake_chain(output: str):
    async def fake(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(output, encoding="utf-8")
    return fake


def _write_stub_wav(path, *, seconds: float = 0.4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * int(16000 * seconds))


def _stub_synth(monkeypatch, *, fail: bool = False):
    async def synth(text, preset_id, out_path):
        if fail:
            raise RuntimeError("synth boom")
        _write_stub_wav(out_path)
    monkeypatch.setattr(voice, "_synth_to_wav", synth)


def _set_caps(monkeypatch, caps):
    monkeypatch.setattr(voice, "get_local_capabilities", lambda: set(caps))


def _seed(config: dict) -> str:
    conv = store.create_conversation({
        "title": "Late-night diner",
        "counterpart_character_id": "mara-okafor",
        "scenario": "1am, rain outside.",
        "role_instructions": "Stay in character as Mara.",
        "device_user": {"display_name": "You", "persona": "A regular."},
        "config": config,
    })
    return conv["id"]


# ---- voice on: dialogue + narration get audio, action does not -------------

async def test_voice_enabled_sets_audio_and_writes_media(monkeypatch):
    _set_caps(monkeypatch, {"voice"})
    _stub_synth(monkeypatch)
    settings_store.update_settings({"narrator_voice_preset_id": _NARRATOR_VOICE})
    conv_id = _seed({"voice_enabled": True})

    turn, _ = await generator.run_model_turn(conv_id)
    by_type = {i["type"]: i for i in turn["items"]}

    # dialogue -> counterpart voice
    assert by_type["dialogue"]["audio"]["voice_preset_id"] == _CP_VOICE
    assert by_type["dialogue"]["audio"]["path"] == f"media/{by_type['dialogue']['id']}.wav"
    assert by_type["dialogue"]["audio"]["duration_ms"] > 0
    # narration -> narrator voice
    assert by_type["narration"]["audio"]["voice_preset_id"] == _NARRATOR_VOICE
    # action is never spoken
    assert by_type["action"]["audio"] is None

    media = store.media_dir(conv_id)
    assert (media / f"{by_type['dialogue']['id']}.wav").exists()
    assert (media / f"{by_type['narration']['id']}.wav").exists()
    assert not (media / f"{by_type['action']['id']}.wav").exists()

    # audio round-trips on disk + the trace carries the reveal schedule
    persisted = store.get_transcript(conv_id)["turns"][-1]
    assert next(i for i in persisted["items"] if i["type"] == "dialogue")["audio"]
    trace = json.loads(store._trace_path(conv_id, turn["id"]).read_text(encoding="utf-8"))
    assert trace["voice_error"] is None
    assert len(trace["reveal_schedule"]) == 3


# ---- degrade-to-text paths -------------------------------------------------

async def test_voice_disabled_is_text_only(monkeypatch):
    _set_caps(monkeypatch, {"voice"})
    _stub_synth(monkeypatch)
    conv_id = _seed({"voice_enabled": False})

    turn, _ = await generator.run_model_turn(conv_id)
    assert all(i["audio"] is None for i in turn["items"])
    assert not store.media_dir(conv_id).exists()


async def test_missing_voice_capability_is_text_only(monkeypatch):
    _set_caps(monkeypatch, set())  # no "voice" here
    _stub_synth(monkeypatch)
    conv_id = _seed({"voice_enabled": True})

    turn, _ = await generator.run_model_turn(conv_id)
    assert all(i["audio"] is None for i in turn["items"])
    assert not store.media_dir(conv_id).exists()


async def test_dialogue_without_counterpart_preset_skips_audio(monkeypatch):
    _set_caps(monkeypatch, {"voice"})
    _stub_synth(monkeypatch)
    monkeypatch.setattr(generator, "get_character",
                        lambda cid: {"id": "mara-okafor", "name": "Mara"})  # no voice preset
    settings_store.update_settings({"narrator_voice_preset_id": _NARRATOR_VOICE})
    conv_id = _seed({"voice_enabled": True})

    turn, _ = await generator.run_model_turn(conv_id)
    by_type = {i["type"]: i for i in turn["items"]}
    assert by_type["dialogue"]["audio"] is None          # no counterpart voice
    assert by_type["narration"]["audio"]["voice_preset_id"] == _NARRATOR_VOICE


async def test_synth_failure_leaves_committed_text_turn(monkeypatch):
    _set_caps(monkeypatch, {"voice"})
    _stub_synth(monkeypatch, fail=True)
    settings_store.update_settings({"narrator_voice_preset_id": _NARRATOR_VOICE})
    conv_id = _seed({"voice_enabled": True})

    turn, _ = await generator.run_model_turn(conv_id)
    # the text reply is intact and committed; just no audio + no stray files
    assert [i["type"] for i in turn["items"]] == ["dialogue", "narration", "action"]
    assert all(i["status"] == "committed" for i in turn["items"])
    assert all(i["audio"] is None for i in turn["items"])
    media = store.media_dir(conv_id)
    assert not media.exists() or not any(media.iterdir())
