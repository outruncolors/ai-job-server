"""use_speakerphone — call another resident on the speakerphone.

Phase 4 stub: records the intent as an event. The real behavior — an atomic
phone-call chain sequence where the callee accepts/declines and the two trade
utterances, with the callee forfeiting its own action that tick — is wired in
Phase 6 (``call_sequence.run_call``).
"""

from __future__ import annotations

from .. import rooms
from .base import Action


async def _run(resident, tick, context, args, deps=None):
    return {
        "action": "use_speakerphone",
        "room_id": rooms.room_of(resident["id"]),
        "payload": {"summary": "reached for the speakerphone (no call placed yet)"},
    }


action = Action(
    name="use_speakerphone",
    description="Use the speakerphone to call another resident for a conversation.",
    run=_run,
)
