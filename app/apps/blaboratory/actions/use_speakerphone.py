"""use_speakerphone — call another resident on the speakerphone.

Picks a random other occupant and runs the atomic phone-call sequence
(``call_sequence.run_call``) inside the caller's tick: the callee accepts or
declines from its own context, and on accept the two trade lines while the
callee forfeits its own action (marked busy on ``deps``). The lines surface in
both rooms; this action contributes the caller's top-level event.
"""

from __future__ import annotations

from .. import rooms
from .base import Action


async def _run(resident, tick, context, args, deps=None):
    from ..call_sequence import pick_callee, run_call

    room_id = rooms.room_of(resident["id"])
    llm = getattr(deps, "llm", None)
    busy = getattr(deps, "busy", set())

    callee = pick_callee(resident["id"], busy=busy) if llm is not None else None
    if callee is None:
        return {
            "action": "use_speakerphone",
            "room_id": room_id,
            "payload": {"summary": "picked up the speakerphone but had no one to call"},
        }

    result = await run_call(resident, callee, tick, llm, deps=deps)
    if result["accepted"]:
        summary = f"called {callee['name']} and talked ({result['lines']} lines)"
    else:
        summary = f"called {callee['name']} — no answer"
    return {
        "action": "use_speakerphone",
        "room_id": room_id,
        "payload": {
            "summary": summary,
            "callee_id": callee["id"],
            "call_id": result["call_id"],
            "accepted": result["accepted"],
        },
    }


action = Action(
    name="use_speakerphone",
    description="Use the speakerphone to call another resident for a conversation.",
    run=_run,
)
