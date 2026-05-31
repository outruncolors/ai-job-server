"""App-level Prattletale settings (a small Config doc).

Currently one knob: the **narrator** voice preset used to synthesize model
``narration`` / ``narration_emotion`` items. Model ``dialogue`` uses the
*counterpart's* own Hoodat voice; the narrator is the app-wide voice for
scene/emotion beats. Flat JSON at ``config/prattletale/settings.json`` (atomic
write). Tests monkeypatch :data:`SETTINGS_PATH`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SETTINGS_PATH: Path = PROJECT_ROOT / "config" / "prattletale" / "settings.json"

_DEFAULTS: dict = {"narrator_voice_preset_id": None}


class SettingsError(ValueError):
    """Raised on an invalid settings patch (router maps to 422)."""


def get_settings() -> dict:
    """Current settings, env-defaulted then file-overridden. Tolerant of a missing
    or corrupt file (falls back to defaults)."""
    data = dict(_DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}
        if isinstance(stored, dict):
            for key in _DEFAULTS:
                if key in stored:
                    data[key] = stored[key]
    return data


def update_settings(patch: dict) -> dict:
    """Validate + persist a settings patch (only known keys). Returns the merged doc."""
    if not isinstance(patch, dict):
        raise SettingsError("patch must be an object")
    current = get_settings()
    if "narrator_voice_preset_id" in patch:
        value = patch["narrator_voice_preset_id"]
        if value is not None and not isinstance(value, str):
            raise SettingsError("narrator_voice_preset_id must be a string or null")
        current["narrator_voice_preset_id"] = value or None

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)
    return current


def narrator_voice_preset_id() -> Optional[str]:
    """The narrator voice preset id, or None when unset."""
    return get_settings().get("narrator_voice_preset_id")
