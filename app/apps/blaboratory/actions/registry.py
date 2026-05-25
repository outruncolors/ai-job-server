"""Action registry — mirrors ``app/mcp/registry.py``.

The first sim-slice action set. ``list_actions`` / ``get_action`` are the lookup
surface used by the tick runner and the decision prompt.
"""

from __future__ import annotations

from typing import Optional

from . import idle, sleep, use_computer, use_speakerphone, use_televisor
from .base import Action

ACTIONS: dict[str, Action] = {
    a.name: a
    for a in (
        use_computer.action,
        use_televisor.action,
        use_speakerphone.action,
        sleep.action,
        idle.action,
    )
}


def list_actions() -> list[Action]:
    return list(ACTIONS.values())


def get_action(name: str) -> Optional[Action]:
    return ACTIONS.get(name)
