"""The Command plugin registration + its ``send`` action.

The ``send`` action persists a user ``command`` turn (an out-of-character order)
and then runs the model turn so the partner replies obeying it. It returns both
turns for the frontend to render. Editing/deleting active commands reuses the
generic per-item REST endpoints (``PATCH``/``DELETE`` ``…/turns/{turn}/items/{item}``)
— this plugin owns no edit/delete action of its own.

A failed validation raises :class:`ValueError` (dispatch maps it → 422).
:func:`run_model_turn` never raises: on failure it returns a ``system_error`` turn
as ``model_turn`` (the frontend renders it as a retry bubble); the command turn is
committed either way.
"""

from __future__ import annotations

from app.apps.prattletale import store
from app.apps.prattletale.generator import run_model_turn

from ..base import Plugin
from ..registry import register

# Frontend assets, loaded by the page only when the plugin is enabled. Paths are
# relative to ``static/``.
_FRONTEND = [
    "apps/prattletale/plugins/command/command.js",
    "apps/prattletale/plugins/command/command.css",
]


async def run_send_command(conversation_id: str, params: dict) -> dict:
    """Persist a ``command`` turn, then generate the obeying reply.

    ``params``: ``{text: str}`` — the order the partner must follow. Empty text or a
    missing conversation raises :class:`ValueError` (→ 422). Returns
    ``{command_turn, model_turn}``."""
    text = (params.get("text") or "").strip()
    if not text:
        raise ValueError("command text must not be empty")
    if store.get_conversation(conversation_id) is None:
        raise ValueError(f"conversation not found: {conversation_id}")

    command_turn = store.append_command_turn(conversation_id, text)
    if command_turn is None:  # pragma: no cover — conversation checked above
        raise ValueError("failed to persist command turn")

    # synthesize=False: the live chat path synthesizes each message lazily.
    model_turn, _job_id = await run_model_turn(conversation_id, synthesize=False)
    return {"command_turn": command_turn, "model_turn": model_turn}


plugin = Plugin(
    id="command",
    name="Command",
    description="Issue an out-of-character order the AI must obey on its next reply.",
    frontend=_FRONTEND,
    actions={"send": run_send_command},
    default_enabled=True,
)

register(plugin)
