"""use_televisor — watch the televisor to catch up on broadcast news.

Consuming news advances the resident's ``news`` cursor. The news *feed* itself
(the lore-building news generator) is deferred, so for now this is largely a
stub: there are no news rows to advance past yet, and the cursor advance is a
no-op until a feed exists.
"""

from __future__ import annotations

from .. import rooms
from .base import Action


async def _run(resident, tick, context, args, deps=None):
    return {
        "action": "use_televisor",
        "room_id": rooms.room_of(resident["id"]),
        "consume": ["news"],
        "payload": {"summary": "watched the televisor"},
    }


action = Action(
    name="use_televisor",
    description="Watch the televisor to catch up on the latest broadcast news.",
    run=_run,
)
