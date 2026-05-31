"""scripts/import_sfx_pack.py — filename/folder parsing, durations, pitch variants."""

from __future__ import annotations

import importlib.util
import math
import struct
import wave
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_importer():
    spec = importlib.util.spec_from_file_location(
        "import_sfx_pack", _ROOT / "scripts" / "import_sfx_pack.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


imp = _load_importer()


def test_slug_splits_camelcase():
    assert imp.slug("DryPlaps") == "dry_plaps"
    assert imp.slug("PullOut") == "pull_out"
    assert imp.slug("Cum") == "cum"


def test_identity_mapping():
    from app.sfx.models import identity_for
    assert identity_for("Woman", "40s") == "mature_woman"
    assert identity_for("Girl", "Teen") == "teen_girl"
    assert identity_for("Boy", "Kid") == "little_boy"
    assert identity_for("Man", "20s") == "young_man"
    assert identity_for("Woman", "70s") == "elderly_woman"
    assert identity_for("Alien", "Kid") is None


def test_parse_emote_filename():
    meta = imp.parse_emote_filename("VOXCry_Emote Chloe, Teen, Sadness Cry Long 02_ASD.wav")
    assert meta["category"] == "cry"
    assert meta["description"] == "Sadness Cry Long"
    assert "sadness" in meta["tags"] and "cry" in meta["tags"]
    assert imp.parse_emote_filename("ZZZUnknown_foo.wav") is None  # unknown prefix


def test_parse_speaker_folder():
    assert imp.parse_speaker_folder("EMOTE Ashley, Woman, 40s") == ("Woman", "40s")
    assert imp.parse_speaker_folder("not a speaker") is None


def _write_wav(path: Path, seconds=0.2, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 150 * i / rate)))
            for i in range(n))
        w.writeframes(frames)


def test_wav_duration_ms(tmp_path):
    p = tmp_path / "a.wav"
    _write_wav(p, seconds=0.25)
    assert abs(imp.wav_duration_ms(p) - 250) <= 5


def test_pitch_variant_generation_and_idempotent(tmp_path):
    pytest.importorskip("parselmouth")
    src = tmp_path / "src.wav"
    _write_wav(src, seconds=0.3, rate=96000)  # like the real packs; exercises downsample
    dst = tmp_path / "out_high.wav"
    assert imp.write_pitch_variant(src, dst, formant=1.10, pitch=1.15) is True
    assert dst.exists()
    mtime = dst.stat().st_mtime_ns
    # Re-running is a no-op (idempotent) — file untouched.
    assert imp.write_pitch_variant(src, dst, formant=1.10, pitch=1.15) is True
    assert dst.stat().st_mtime_ns == mtime
    # Derivative is a valid, downsampled WAV.
    with wave.open(str(dst)) as w:
        assert w.getframerate() == imp.DERIVATIVE_SAMPLE_RATE
        assert w.getnframes() > 0
