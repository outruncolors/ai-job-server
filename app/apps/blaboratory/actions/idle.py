"""idle — do nothing of note this tick."""

from __future__ import annotations

from .. import rooms
from .base import Action


async def _run(resident, tick, context, args, deps=None):
    return {
        "action": "idle",
        "room_id": rooms.room_of(resident["id"]),
        "payload": {"summary": "idled, lost in thought"},
    }


action = Action(
    name="idle",
    description="Do nothing in particular — daydream or potter about.",
    run=_run,
)
