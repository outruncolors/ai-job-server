"""Tests for SFX synthesis: combining WAV clips with delays, save/list/delete."""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from app.sfx import store, synthesis


def _write_wav(path, seconds=0.2, rate=16000, freq=220):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(n)))


@pytest.fixture()
def synth_env(tmp_path, monkeypatch):
    """A tmp SFX_ROOT with two real WAV clips, plus a tmp synthesis store."""
    root = tmp_path / "sfx"
    (root / "clips").mkdir(parents=True, exist_ok=True)
    _write_wav(root / "clips" / "a.wav", seconds=0.20)
    _write_wav(root / "clips" / "b.wav", seconds=0.10, freq=440)
    (root / "clips" / "c.ogg").write_bytes(b"OggSfake")  # unsupported decode

    monkeypatch.setattr(store, "SFX_ROOT", root)
    monkeypatch.setattr(synthesis, "SYNTH_DIR", tmp_path / "synth")
    monkeypatch.setattr(synthesis, "INDEX_PATH", tmp_path / "synth" / "index.json")
    return root


def _wav_params(data: bytes):
    with wave.open(io.BytesIO(data)) as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()


def test_synthesize_combines_with_delay(synth_env):
    wav, duration_ms = synthesis.synthesize([
        {"path": "clips/a.wav", "delay_ms": 100},
        {"path": "clips/b.wav", "delay_ms": 0},
    ])
    rate, ch, width, frames = _wav_params(wav)
    assert (rate, ch, width) == (synthesis.TARGET_RATE, 1, 2)
    # 200ms + 100ms gap + 100ms ≈ 400ms (allow resampling slack).
    assert 380 <= duration_ms <= 420
    assert frames == int(round(duration_ms / 1000 * rate)) or abs(
        frames - duration_ms / 1000 * rate) < rate * 0.05


def test_trailing_delay_dropped(synth_env):
    """The last clip's delay_ms never adds trailing silence."""
    _, with_gap = synthesis.synthesize([{"path": "clips/a.wav", "delay_ms": 500}])
    _, no_gap = synthesis.synthesize([{"path": "clips/a.wav", "delay_ms": 0}])
    assert with_gap == no_gap


def test_empty_clips_raises(synth_env):
    with pytest.raises(synthesis.SynthesisError):
        synthesis.synthesize([])


def test_unsupported_format_raises(synth_env):
    with pytest.raises(synthesis.SynthesisError, match="WAV only"):
        synthesis.synthesize([{"path": "clips/c.ogg", "delay_ms": 0}])


def test_missing_clip_raises(synth_env):
    with pytest.raises(synthesis.SynthesisError, match="not found"):
        synthesis.synthesize([{"path": "clips/nope.wav", "delay_ms": 0}])


def test_save_list_path_delete_roundtrip(synth_env):
    clips = [{"path": "clips/a.wav", "delay_ms": 50}, {"path": "clips/b.wav", "delay_ms": 0}]
    rec = synthesis.save_sample("My Combo", clips)
    assert rec["name"] == "My Combo"
    assert rec["duration_ms"] > 0
    assert rec["clips"] == clips

    samples = synthesis.list_samples()
    assert [s["id"] for s in samples] == [rec["id"]]

    path = synthesis.sample_path(rec["id"])
    assert path is not None and path.exists()
    assert path.read_bytes()[:4] == b"RIFF"

    assert synthesis.delete_sample(rec["id"]) is True
    assert synthesis.list_samples() == []
    assert synthesis.sample_path(rec["id"]) is None
    assert synthesis.delete_sample(rec["id"]) is False


def test_blank_name_falls_back(synth_env):
    rec = synthesis.save_sample("   ", [{"path": "clips/a.wav", "delay_ms": 0}])
    assert rec["name"] == "Untitled"
