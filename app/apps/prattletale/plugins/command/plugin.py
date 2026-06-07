"""The Command plugin registration + its ``send`` action.

A command is a **standing order** — a switch the user flips on. The ``send`` action
persists a user ``command`` turn (the moment the switch was flipped) and returns it;
it does **not** generate a partner reply. The order then stays in force, injected as
a STANDING ORDERS block into every future turn (see ``generator._collect_standing_orders``),
until the user hides or deletes the command item — switching it back off — via the
generic per-item REST endpoints (``PATCH``/``DELETE`` ``…/turns/{turn}/items/{item}``).
This plugin owns no edit/delete action of its own.

A failed validation raises :class:`ValueError` (dispatch maps it → 422).
"""

from __future__ import annotations

from app.apps.prattletale import store

from ..base import Plugin
from ..registry import register

# Frontend assets, loaded by the page only when the plugin is enabled. Paths are
# relative to ``static/``.
_FRONTEND = [
    "apps/prattletale/plugins/command/command.js",
    "apps/prattletale/plugins/command/command.css",
]


async def run_send_command(conversation_id: str, params: dict) -> dict:
    """Persist a ``command`` turn — switching a standing order on. The partner does
    **not** reply to the command itself; the order takes effect on the next normal
    turn and stays in force until switched off.

    ``params``: ``{text: str}`` — the order to switch on. Empty text or a missing
    conversation raises :class:`ValueError` (→ 422). Returns ``{command_turn}``."""
    text = (params.get("text") or "").strip()
    if not text:
        raise ValueError("command text must not be empty")
    if store.get_conversation(conversation_id) is None:
        raise ValueError(f"conversation not found: {conversation_id}")

    command_turn = store.append_command_turn(conversation_id, text)
    if command_turn is None:  # pragma: no cover — conversation checked above
        raise ValueError("failed to persist command turn")

    return {"command_turn": command_turn}


plugin = Plugin(
    id="command",
    name="Command",
    description="Switch on an out-of-character standing order the AI obeys on every reply.",
    frontend=_FRONTEND,
    actions={"send": run_send_command},
    default_enabled=True,
)

register(plugin)
