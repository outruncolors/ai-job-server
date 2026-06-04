"""The Remember plugin package — importing it registers the plugin (and its
Prompt Pal entries) via ``plugin.py``."""

from __future__ import annotations

from . import plugin  # noqa: F401 — import side effect: register()

__all__ = ["plugin"]
