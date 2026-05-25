"""Room occupancy store for Blaboratory.

There are 16 fixed rooms (#1–#16). Occupancy is deliberately a *separate* store
from the resident document — a room maps to a resident id (or `null`). State
lives in `config/blaboratory/occupancy.json` as `{ "1": "<id>"|null, … }` for
all 16 rooms. Invariants: room id in 1–16; `set_occupant` refuses an
out-of-range room and refuses to overwrite an occupied one. Atomic writes,
monkeypatchable `OCCUPANCY_PATH`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OCCUPANCY_PATH: Path = PROJECT_ROOT / "config" / "blaboratory" / "occupancy.json"

ROOM_IDS = range(1, 17)


def _require_valid_room(room_id: int) -> None:
    if room_id not in ROOM_IDS:
        raise ValueError(f"room_id out of range: {room_id} (must be 1–16)")


def _read() -> dict[str, Optional[str]]:
    if not OCCUPANCY_PATH.exists():
        return {str(r): None for r in ROOM_IDS}
    stored = json.loads(OCCUPANCY_PATH.read_text(encoding="utf-8"))
    # Always normalize to all 16 rooms, regardless of what's on disk.
    return {str(r): stored.get(str(r)) for r in ROOM_IDS}


def _atomic_write(data: dict[str, Optional[str]]) -> None:
    OCCUPANCY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OCCUPANCY_PATH.with_suffix(OCCUPANCY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, OCCUPANCY_PATH)


def list_occupancy() -> dict[str, Optional[str]]:
    """Occupancy for all 16 rooms (string keys "1".."16" → resident id|None)."""
    return _read()


def get_room(room_id: int) -> Optional[str]:
    """Resident id occupying `room_id`, or None if empty."""
    _require_valid_room(room_id)
    return _read()[str(room_id)]


def is_empty(room_id: int) -> bool:
    return get_room(room_id) is None


def room_of(resident_id: str) -> Optional[int]:
    """The room a resident occupies, or None if they're not placed."""
    for room_id, occ in _read().items():
        if occ == resident_id:
            return int(room_id)
    return None


def occupied_rooms() -> list[tuple[int, str]]:
    """(room_id, resident_id) pairs for every occupied room, ascending by room."""
    occ = _read()
    return [(int(r), occ[str(r)]) for r in ROOM_IDS if occ[str(r)] is not None]


def set_occupant(room_id: int, resident_id: str) -> None:
    """Place a resident in a room. Rejects out-of-range rooms and refuses to
    overwrite an already-occupied room.
    """
    _require_valid_room(room_id)
    occ = _read()
    if occ[str(room_id)] is not None:
        raise ValueError(f"room {room_id} is already occupied")
    occ[str(room_id)] = resident_id
    _atomic_write(occ)


def clear_room(room_id: int) -> None:
    _require_valid_room(room_id)
    occ = _read()
    occ[str(room_id)] = None
    _atomic_write(occ)
