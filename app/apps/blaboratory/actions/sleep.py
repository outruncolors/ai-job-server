"""sleep — a multi-tick activity, started once and Continued.

Breakpoints nudge the resident awake as the nap drags on (the clause is composed
into the per-tick decision prompt once ``count`` crosses each threshold).
"""

from __future__ import annotations

from .. import rooms
from .base import Action


async def _run(resident, tick, context, args, deps=None):
    return {
        "action": "sleep",
        "room_id": rooms.room_of(resident["id"]),
        "payload": {"summary": "slept"},
    }


action = Action(
    name="sleep",
    description="Sleep. You'll stay asleep across ticks until you choose to wake.",
    run=_run,
    multi_tick=True,
    breakpoints=[
        {"count": 3, "breakpoint": "You've been asleep a while; you may wake soon."},
        {"count": 6, "breakpoint": "You've slept a long time — you should wake up now."},
    ],
)
