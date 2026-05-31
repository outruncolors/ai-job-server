"""Synthesize combined SFX samples: concatenate clips with silence gaps.

WAV-only for now — parselmouth (the only decoder available) can't read the OGG
packs and there's no system decoder; non-WAV inputs raise ``SynthesisError``.
Output is 48 kHz mono 16-bit WAV. Saved samples live in the gitignored
``config/sfx_synthesis/`` tree (``index.json`` + ``<id>.wav``), mirroring the
voice-presets layout.
"""

from __future__ import annotations

import io
import json
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from app.omnivoice.config import PROJECT_ROOT

from . import store

TARGET_RATE = 48000
SYNTH_DIR: Path = PROJECT_ROOT / "config" / "sfx_synthesis"
INDEX_PATH: Path = SYNTH_DIR / "index.json"


class SynthesisError(ValueError):
    """A synthesis request that can't be fulfilled (empty / missing / unsupported clip)."""


# ── Audio assembly ─────────────────────────────────────────────────────────

def _load_mono_48k(rel_path: str) -> np.ndarray:
    """Resolve a clip under SFX_ROOT → float32 mono samples at TARGET_RATE."""
    path = store.resolve_file_path(rel_path)
    if path is None:
        raise SynthesisError(f"clip not found: {rel_path}")
    if path.suffix.lower() != ".wav":
        raise SynthesisError(f"unsupported format (WAV only for now): {path.name}")
    try:
        import parselmouth
        from parselmouth.praat import call

        sound = parselmouth.Sound(str(path))
        if abs(sound.sampling_frequency - TARGET_RATE) > 1:
            sound = call(sound, "Resample", TARGET_RATE, 50)
        if sound.n_channels > 1:
            sound = call(sound, "Convert to mono")
        values = sound.values
        arr = values[0] if values.ndim == 2 else values
        return np.asarray(arr, dtype=np.float32)
    except SynthesisError:
        raise
    except Exception as exc:  # decode failure
        raise SynthesisError(f"could not decode {path.name}: {exc}") from exc


def _assemble(clips: list[dict]) -> np.ndarray:
    """Concatenate clip samples, inserting each clip's ``delay_ms`` of silence
    after it (the trailing gap of the last clip is dropped)."""
    if not clips:
        raise SynthesisError("no clips to synthesize")
    parts: list[np.ndarray] = []
    last = len(clips) - 1
    for i, clip in enumerate(clips):
        parts.append(_load_mono_48k(clip.get("path", "")))
        delay_ms = int(clip.get("delay_ms") or 0)
        if i < last and delay_ms > 0:
            parts.append(np.zeros(int(TARGET_RATE * delay_ms / 1000), dtype=np.float32))
    return np.concatenate(parts)


def _to_wav_bytes(samples: np.ndarray) -> bytes:
    pcm16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()


def synthesize(clips: list[dict]) -> tuple[bytes, int]:
    """Combine ``clips`` (each ``{path, delay_ms}``) → (wav_bytes, duration_ms)."""
    samples = _assemble(clips)
    duration_ms = int(round(len(samples) / TARGET_RATE * 1000))
    return _to_wav_bytes(samples), duration_ms


# ── Saved samples ──────────────────────────────────────────────────────────

def _load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_index(records: list[dict]) -> None:
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def list_samples() -> list[dict]:
    return _load_index()


def save_sample(name: str, clips: list[dict]) -> dict:
    """Synthesize and persist a sample; returns its index record."""
    wav_bytes, duration_ms = synthesize(clips)
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    sample_id = uuid.uuid4().hex
    wav_filename = f"{sample_id}.wav"
    (SYNTH_DIR / wav_filename).write_bytes(wav_bytes)
    record = {
        "id": sample_id,
        "name": (name or "").strip() or "Untitled",
        "clips": clips,
        "duration_ms": duration_ms,
        "wav_filename": wav_filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    records = _load_index()
    records.append(record)
    _write_index(records)
    return record


def sample_path(sample_id: str) -> Optional[Path]:
    rec = next((r for r in _load_index() if r.get("id") == sample_id), None)
    if rec is None:
        return None
    p = SYNTH_DIR / rec["wav_filename"]
    return p if p.exists() else None


def delete_sample(sample_id: str) -> bool:
    records = _load_index()
    rec = next((r for r in records if r.get("id") == sample_id), None)
    if rec is None:
        return False
    try:
        (SYNTH_DIR / rec["wav_filename"]).unlink(missing_ok=True)
    except Exception:
        pass
    _write_index([r for r in records if r.get("id") != sample_id])
    return True
