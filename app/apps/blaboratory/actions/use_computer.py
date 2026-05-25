"""use_computer — catch up on the shared chat feed, optionally posting a message.

Consuming the chat is what advances this resident's chat cursor (visibility =
consumption). An optional ``post`` arg appends a message to the feed; the cursor
then advances past it too (see ``context_pipeline.write_phase``).
"""

from __future__ import annotations

from .. import rooms
from .base import Action


async def _run(resident, tick, context, args, deps=None):
    args = args or {}
    post = args.get("post")
    if isinstance(post, str):
        post = post.strip() or None
    else:
        post = None
    summary = "checked the computer chat" + (" and posted a message" if post else "")
    return {
        "action": "use_computer",
        "room_id": rooms.room_of(resident["id"]),
        "consume": ["chat"],
        "chat_post": post,
        "payload": {"summary": summary, "post": post},
    }


action = Action(
    name="use_computer",
    description=(
        "Sit at the computer to read the shared chat feed and catch up on what "
        "others have said. Optionally post your own message via the \"post\" arg."
    ),
    run=_run,
)
