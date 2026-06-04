"""The Command plugin — an out-of-character override channel.

A composer **⚡ Command** mode that posts a user ``command`` item: an order the AI
partner must obey on its next reply, even against its character, wishes, or the
scenario. Commands are persistent (every active command stays in force) and render
as a distinct blue-bordered card. A header **⚡ N** indicator opens a manager modal
where active commands can be edited or deleted.

The obligation language lives in the flattened transcript
(:func:`app.apps.prattletale.generator._render_item`), so compliance does not
depend on the editable ``turn`` prompt. The frontend (``command.js`` /
``command.css``) supplies the composer mode, the bubble renderer, and the
active-commands manager; this package only wires the ``send`` action.
"""

from . import plugin  # noqa: F401 — registers the plugin when the package is imported
