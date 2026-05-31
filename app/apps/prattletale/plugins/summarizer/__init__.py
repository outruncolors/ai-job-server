"""The Summarizer plugin — Prattletale's first plugin.

A composer **📋 Summarize** mode that condenses the conversation so far into a
single ``summary`` item via a hierarchical map-reduce over the chain executor.
**Keep** posts the recap alongside the originals; **Purge** also hides the covered
originals so the summary compresses the context window.

Modules:
- :mod:`.prompts` — the editable Prompt Pal entries (``summarize.map`` /
  ``summarize.reduce`` / ``summarize.level.{brief,standard,detailed}``).
- :mod:`.summarize` — the map-reduce engine (``summarize_history``).
- :mod:`.plugin` — the :class:`~app.apps.prattletale.plugins.base.Plugin`
  registration + the ``summarize`` action (SP3).
"""

from . import plugin  # noqa: F401 — registers the plugin when the package is imported
