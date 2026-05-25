"""Action plugin contract for the Blaboratory simulation.

An **action** is a self-contained thing a resident can do on its tick (mirrors a
chain step-runner + MCP tool). Each declares how it presents itself to the LLM
(``name`` / ``description``), whether it spans multiple ticks (``multi_tick`` —
e.g. ``sleep`` is started once and Continued), and its **breakpoints**: as an
ongoing activity's ``count`` climbs, the matching clause is composed into the
per-tick decision prompt to nudge the resident toward wrapping up.

``run`` performs the action: it returns an *action result* dict (the contract
consumed by ``context_pipeline.write_phase``):

    {
      "action": str, "kind": str = "action", "room_id": int | None,
      "payload": dict | None, "chat_post": str | None, "consume": [channels...],
    }

``deps`` carries per-tick shared state (the busy set, the resolved LLM config);
simple actions ignore it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

ActionResult = dict[str, Any]
ActionRunner = Callable[..., Awaitable[ActionResult]]


@dataclass
class Action:
    name: str
    description: str
    run: ActionRunner
    multi_tick: bool = False
    # Ordered ascending by count; each: {"count": int, "breakpoint": str}.
    breakpoints: list[dict] = field(default_factory=list)


def breakpoint_clause(action: Action, count: int) -> str:
    """The breakpoint clause for an ongoing activity at ``count`` ticks.

    Returns the clause of the highest threshold ``<= count`` (so the nudge gets
    stronger the longer the activity runs), or "" when none applies yet.
    """
    clause = ""
    for bp in sorted(action.breakpoints, key=lambda b: b["count"]):
        if count >= bp["count"]:
            clause = bp["breakpoint"]
    return clause
