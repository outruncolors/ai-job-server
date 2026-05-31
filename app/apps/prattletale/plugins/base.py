"""The plugin contract — the :class:`Plugin` dataclass + its JSON manifest.

A plugin's only backend extension point is a named **action**: an
``async run(conversation_id, params) -> dict`` callable the frontend invokes via
``POST /conversations/{id}/plugins/{plugin_id}/actions/{action}``. The action does
its work (its own LLM runs, store writes) and returns a result dict the frontend
renders — the core never needs to know what the plugin does.

``manifest()`` is the JSON-safe subset surfaced by ``GET /plugins`` (and consumed
by the frontend loader): id/name/description/version/frontend/default_enabled plus
the **action names** (the callables themselves aren't serializable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

# An action: async run(conversation_id, params) -> result dict.
ActionRunner = Callable[[str, dict], Awaitable[dict]]


@dataclass
class Plugin:
    id: str  # kebab id, e.g. "summarizer"
    name: str  # display name
    description: str = ""
    version: str = "1"
    # Frontend assets (JS/CSS) served from the plugin's static dir, loaded by the
    # page only when the plugin is enabled for the conversation. Paths are
    # relative to ``static/`` (e.g. ``apps/prattletale/plugins/summarizer/summarizer.js``).
    frontend: list[str] = field(default_factory=list)
    # action name -> async run(conversation_id, params) -> dict
    actions: dict[str, ActionRunner] = field(default_factory=dict)
    # Whether new conversations get this plugin enabled by default.
    default_enabled: bool = False
    # Optional: a no-arg callable that registers the plugin's Prompt Pal entries,
    # invoked once by the loader at lifespan.
    seed_prompts: Optional[Callable[[], None]] = None

    def manifest(self) -> dict[str, Any]:
        """The JSON-safe subset for ``GET /plugins`` / the frontend loader."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "frontend": list(self.frontend),
            "actions": sorted(self.actions.keys()),
            "default_enabled": self.default_enabled,
        }

    def get_action(self, name: str) -> Optional[ActionRunner]:
        return self.actions.get(name)
