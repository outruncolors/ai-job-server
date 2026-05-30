"""Operator-editable sim settings (hot-applied, file-backed).

The numeric/boolean sim knobs that used to be *only* env vars (tick cadence,
memory caps, hybrid-retrieval sizes) are editable at runtime from the Config
tab. Values live in one flat JSON doc, ``config/blaboratory/settings.json``,
and **override** the env-defaulted constants in :mod:`.config`.

Precedence (same shape as ``clock_state.json``):

    file value  >  env-defaulted constant in config.py

First boot with no file: the getters return the ``config.py`` defaults (which
themselves honour ``BLAB_*`` env vars). The first :func:`update_settings`
writes the full dict; after that the file is the source of truth. Deleting the
file reverts to env defaults.

Consumers call the per-key getters on each access (no in-memory cache to
invalidate) so an edit applies on the *next* tick / context build.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import config

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SETTINGS_PATH: Path = PROJECT_ROOT / "config" / "blaboratory" / "settings.json"

# Knob name → env-defaulted constant in config.py. The keys here are the full
# settings schema; defaults flow from config.py so that file stays the single
# place env-var names + numeric defaults are declared.
_DEFAULTS: dict[str, int] = {
    "tick_interval_seconds": config.TICK_INTERVAL_SECONDS,
    "max_memory_items": config.MAX_MEMORY_ITEMS,
    "max_memory_chars": config.MAX_MEMORY_CHARS,
    "recency_floor_items": config.RECENCY_FLOOR_ITEMS,
    "relevant_top_k": config.RELEVANT_TOP_K,
}

# Per-key inclusive bounds for validation. All knobs are positive ints with a
# sane upper ceiling (tick interval ≤ 1 day; the rest are small counts/budgets).
_BOUNDS: dict[str, tuple[int, int]] = {
    "tick_interval_seconds": (1, 86400),
    "max_memory_items": (1, 1000),
    "max_memory_chars": (1, 1_000_000),
    "recency_floor_items": (1, 1000),
    "relevant_top_k": (1, 1000),
}


class SettingsError(ValueError):
    """Raised on a rejected update; ``field`` names the offending key."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def _read_file() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _atomic_write(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)


def get_settings() -> dict[str, int]:
    """Full settings dict: env-defaulted constants overlaid by file overrides.

    Only known keys are surfaced (unknown keys in the file are ignored), and a
    file value that isn't a valid in-bounds int falls back to the default.
    """
    overrides = _read_file()
    out: dict[str, int] = {}
    for key, default in _DEFAULTS.items():
        value = overrides.get(key, default)
        lo, hi = _BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, int) or not (lo <= value <= hi):
            value = default
        out[key] = value
    return out


def _validate(key: str, value: object) -> int:
    if key not in _DEFAULTS:
        raise SettingsError(key, f"unknown setting: {key}")
    # Reject bools (they're ints in Python) and non-ints up front.
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsError(key, f"{key} must be an integer")
    lo, hi = _BOUNDS[key]
    if not (lo <= value <= hi):
        raise SettingsError(key, f"{key} must be between {lo} and {hi}")
    return value


def update_settings(patch: dict) -> dict[str, int]:
    """Validate a **partial** patch, merge over current settings, persist, return full.

    Raises :class:`SettingsError` (with ``.field``) on the first bad key/value;
    nothing is written when validation fails.
    """
    validated = {key: _validate(key, value) for key, value in patch.items()}
    merged = {**get_settings(), **validated}
    _atomic_write(merged)
    return merged


# ---- per-key getters (consumers call these on each access) ----------------


def tick_interval_seconds() -> int:
    return get_settings()["tick_interval_seconds"]


def max_memory_items() -> int:
    return get_settings()["max_memory_items"]


def max_memory_chars() -> int:
    return get_settings()["max_memory_chars"]


def recency_floor_items() -> int:
    return get_settings()["recency_floor_items"]


def relevant_top_k() -> int:
    return get_settings()["relevant_top_k"]
