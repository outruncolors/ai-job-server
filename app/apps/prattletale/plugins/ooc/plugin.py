"""The OOC plugin registration + its ``send`` action.

A composer **⌁ OOC** mode opens a parallel, out-of-character chat with the author
behind the character. The ``send`` action posts the user's OOC message, generates
the author's reply (:func:`generate.generate_ooc_reply`), and returns **both**
turns. The user keeps replying in OOC mode to continue the side-chat; sending a
normal (Essentials) message concludes the session — a "session" is just a
maximal run of consecutive ``ooc`` items, so the next in-character turn ends it
for free, and the run renders as a collapsible "out of character" panel.

In-character turns never see OOC content (the ``ooc`` item type is filtered out
of ``generator._flatten_transcript``); OOC generation, in turn, sees the full
in-character window plus the entire OOC history (``generator.render_ooc_history``)
so a later session carries the earlier ones forward.

A failed validation raises :class:`ValueError` (dispatch maps it → 422). A failed
*generation* does not raise — it posts an inline-error OOC reply (see
:mod:`generate`).
"""

from __future__ import annotations

from app.apps.prattletale import store
from app.apps.prattletale.models import Author

from ..base import Plugin
from ..registry import register
from . import prompts  # noqa: F401 — registers the ooc.reply Prompt Pal default on import
from .generate import generate_ooc_reply

# Frontend assets, loaded by the page only when the plugin is enabled. Paths are
# relative to ``static/``.
_FRONTEND = [
    "apps/prattletale/plugins/ooc/ooc.js",
    "apps/prattletale/plugins/ooc/ooc.css",
]


async def run_ooc_send(conversation_id: str, params: dict) -> dict:
    """Post the user's OOC message, then generate the author's reply.

    ``params``: ``{text: str}`` — the out-of-character message. Empty text or a
    missing conversation raises :class:`ValueError` (→ 422). Returns
    ``{ooc_user_turn, ooc_model_turn}`` (both are appended to the transcript)."""
    text = (params.get("text") or "").strip()
    if not text:
        raise ValueError("OOC message must not be empty")
    if store.get_conversation(conversation_id) is None:
        raise ValueError(f"conversation not found: {conversation_id}")

    user_turn = store.append_ooc_turn(conversation_id, Author.user, text)
    if user_turn is None:  # pragma: no cover — conversation checked above
        raise ValueError("failed to persist OOC message")

    # The user turn is now at the tail of the OOC history; the reply answers it.
    model_turn, _job_id = await generate_ooc_reply(conversation_id)
    return {"ooc_user_turn": user_turn, "ooc_model_turn": model_turn}


def _seed_prompts() -> None:
    """Seed the OOC Prompt Pal entry (the ``prompts`` module's register() ran on
    import). Seed-if-absent, idempotent."""
    from app.prompt_pal.registry import seed_registered

    seed_registered()


plugin = Plugin(
    id="ooc",
    name="OOC",
    description="Step out of character to talk with the author behind the character.",
    frontend=_FRONTEND,
    actions={"send": run_ooc_send},
    default_enabled=True,
    seed_prompts=_seed_prompts,
)

register(plugin)
