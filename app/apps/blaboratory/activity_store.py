"""Current-activity state per resident.

A multi-tick activity (e.g. ``sleep``) is started once and Continued: this store
records which action a resident is currently engaged in and for how many ticks
(``count``), so the tick runner can offer "continue" and feed the activity's
breakpoint clause into the decision prompt. Single-tick actions clear it.

Stored as one JSON doc, `config/blaboratory/activities.json`:
``{ "<resident_id>": {"action": "sleep", "count": 2}, ... }``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ACTIVITIES_PATH: Path = PROJECT_ROOT / "config" / "blaboratory" / "activities.json"


def _read() -> dict[str, dict]:
    if not ACTIVITIES_PATH.exists():
        return {}
    try:
        return json.loads(ACTIVITIES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _atomic_write(data: dict[str, dict]) -> None:
    ACTIVITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVITIES_PATH.with_suffix(ACTIVITIES_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, ACTIVITIES_PATH)


def get_activity(resident_id: str) -> Optional[dict]:
    """Current activity ``{"action", "count"}`` for a resident, or None."""
    return _read().get(resident_id)


def set_activity(resident_id: str, action: str, count: int) -> None:
    data = _read()
    data[resident_id] = {"action": action, "count": count}
    _atomic_write(data)


def clear_activity(resident_id: str) -> None:
    data = _read()
    if resident_id in data:
        del data[resident_id]
        _atomic_write(data)
