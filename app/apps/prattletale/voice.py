"""Prattletale voice synthesis + reveal timing (SP6).

Additive over the text loop. After a model turn is committed text-first, this
synthesizes audio for its **spoken** items — but only when the conversation has
``config.voice_enabled`` **and** this node holds the ``voice`` capability:

- model ``dialogue`` -> the **counterpart's** Hoodat voice preset
  (``character.speaking_style.voice_preset_id``; skipped if absent);
- every **other** non-error model item (``action`` / ``narration`` /
  ``narration_emotion``) -> the app-level **narrator** voice
  (:func:`app.apps.prattletale.settings_store.narrator_voice_preset_id`);
- ``system_error`` and **all user items** are never synthesized.

Everything degrades cleanly to text: a missing capability, a disabled
conversation, an absent preset, or a synth failure leaves ``item.audio = None``
and writes no media file (a half-written wav is removed). Because the text turn
is already persisted, voice never fails the reply — the generator runs this
best-effort and swallows errors.

:func:`reveal_schedule` is the deterministic per-item timing record written to
the trace; the frontend computes its own jittered cadence for playback.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Optional

from ...server import get_local_capabilities
from ...voice_presets import get_preset, resolve_preset_wav
from . import settings_store, store
from .models import Author, ItemType

# Reveal-cadence tuning (the frontend mirrors these constants for playback).
_MS_PER_CHAR = 28
_MIN_TYPING_MS = 600
_MAX_TYPING_MS = 4500


def _wav_duration_ms(data: bytes) -> int:
    """Clip duration in ms (reuses the wave-module approach from voice_presets_router)."""
    with wave.open(io.BytesIO(data)) as wf:
        return round(wf.getnframes() / wf.getframerate() * 1000)


def voice_active(conversation: dict) -> bool:
    """True when this conversation wants voice **and** this node can synthesize it.

    The capability gate mirrors ``requires_capability('voice')`` without raising —
    a non-voice node simply produces a text-only turn.
    """
    cfg = conversation.get("config") or {}
    return bool(cfg.get("voice_enabled")) and "voice" in get_local_capabilities()


def _preset_for_item(item: dict, character: dict) -> Optional[str]:
    """The voice preset id for a model item, or None if it shouldn't be spoken.

    ``dialogue`` speaks in the counterpart's own Hoodat voice; **every other**
    non-error model item (``action`` / ``narration`` / ``narration_emotion``) is
    spoken by the app-level narrator. Only ``system_error`` is never spoken."""
    item_type = item.get("type")
    if item_type == ItemType.system_error.value:
        return None
    if item_type == ItemType.dialogue.value:
        return ((character.get("speaking_style") or {}).get("voice_preset_id")) or None
    return settings_store.narrator_voice_preset_id()


async def _synth_to_wav(text: str, preset_id: str, out_path: Path) -> None:
    """Synthesize ``text`` in ``preset_id``'s voice to ``out_path`` (wav).

    Isolated as the single TTS boundary so tests can monkeypatch it with a stub
    wav writer (no OmniVoice subprocess needed).
    """
    from ...omnivoice.config import get_config
    from ...omnivoice.runner import OmniVoiceEphemeralRunner

    preset = get_preset(preset_id)
    wav_path = resolve_preset_wav(preset_id)
    if preset is None or wav_path is None:
        raise RuntimeError(f"voice preset {preset_id!r} unusable (missing index entry or wav)")

    config = get_config()
    runner = OmniVoiceEphemeralRunner(config)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    await runner.run(
        text,
        out_path,
        out_path.parent,  # logs.txt lands beside the media
        language=config.language,
        instruct=config.instruct,
        ref_audio_filename=str(wav_path),
        ref_text=preset["caption"],
    )


async def synthesize_item(conversation: dict, character: dict, item: dict) -> Optional[dict]:
    """Synthesize a single spoken model item into the conversation's ``media/`` dir.

    Returns ``{path, duration_ms, voice_preset_id}`` or None when the item isn't
    spoken (voice inactive, wrong type, no preset, empty text) or synthesis fails.
    **Idempotent**: if the wav already exists it is reused (its duration re-read),
    so the per-message lazy path can call this repeatedly without re-synthesizing.
    """
    if not voice_active(conversation):
        return None
    preset_id = _preset_for_item(item, character)
    text = (item.get("text") or "").strip()
    if not preset_id or not text:
        return None

    out_path = store.media_dir(conversation["id"]) / f"{item['id']}.wav"
    if not out_path.exists():
        try:
            await _synth_to_wav(text, preset_id, out_path)
        except Exception:  # noqa: BLE001 — best-effort; leave the item text-only
            if out_path.exists():
                out_path.unlink()
            return None
    try:
        duration_ms = _wav_duration_ms(out_path.read_bytes())
    except Exception:  # noqa: BLE001 — a wav we can't read is unusable
        return None
    return {
        "path": f"media/{item['id']}.wav",
        "duration_ms": duration_ms,
        "voice_preset_id": preset_id,
    }


async def synthesize_turn(conversation: dict, character: dict, turn: dict) -> dict:
    """Synthesize **all** spoken model items of ``turn`` up front (the eager path).

    Returns ``{item_id: {path, duration_ms, voice_preset_id}}`` for the items that
    received audio (empty dict when voice is inactive or nothing was spoken). The
    live chat path drives per-message synthesis via :func:`synthesize_item`
    instead, so the reply isn't blocked on every clip; this stays for callers that
    want a fully-voiced turn in one await.
    """
    if turn.get("author") != Author.model.value or not voice_active(conversation):
        return {}
    audio_map: dict = {}
    for item in turn.get("items") or []:
        audio = await synthesize_item(conversation, character, item)
        if audio:
            audio_map[item["id"]] = audio
    return audio_map


def _typing_ms(text: str) -> int:
    chars = len((text or "").strip())
    return max(_MIN_TYPING_MS, min(_MAX_TYPING_MS, chars * _MS_PER_CHAR))


def reveal_schedule(turn: dict) -> list[dict]:
    """Per-item reveal plan for the trace: a typing duration derived from text
    length plus the clip duration when audio exists. Deterministic (no jitter) —
    the frontend adds its own jitter at playback.
    """
    schedule: list[dict] = []
    for item in turn.get("items") or []:
        audio = item.get("audio") or {}
        schedule.append(
            {
                "item_id": item.get("id"),
                "typing_ms": _typing_ms(item.get("text", "")),
                "audio_ms": int(audio.get("duration_ms") or 0),
            }
        )
    return schedule
