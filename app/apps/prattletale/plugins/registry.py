"""Plugin registry + loader — mirrors Prompt Pal's import-then-seed pattern.

Plugins ``register(...)`` themselves at import time. ``seed_plugins()`` (called
once at lifespan, beside Prompt Pal's ``seed_registered()``) imports every plugin
package explicitly so its registration has run regardless of import order, then
invokes each plugin's optional ``seed_prompts`` to seed its Prompt Pal entries.
"""

from __future__ import annotations

import importlib
from typing import Optional

from .base import Plugin

# Plugin packages that call register() at import time. seed_plugins() imports
# these so registration is guaranteed to have run (like Prompt Pal's
# _PROMPT_MODULES). Add a package here when a new plugin lands.
_PLUGIN_MODULES = (
    "app.apps.prattletale.plugins.summarizer",
    "app.apps.prattletale.plugins.sfx",
    "app.apps.prattletale.plugins.memory",
    "app.apps.prattletale.plugins.command",
    "app.apps.prattletale.plugins.ooc",
)

PLUGIN_REGISTRY: dict[str, Plugin] = {}


def register(plugin: Plugin) -> Plugin:
    """Register a plugin by id. Idempotent on re-import (last declaration wins)."""
    PLUGIN_REGISTRY[plugin.id] = plugin
    return plugin


def get_plugin(plugin_id: str) -> Optional[Plugin]:
    return PLUGIN_REGISTRY.get(plugin_id)


def list_plugins() -> list[Plugin]:
    return list(PLUGIN_REGISTRY.values())


def default_enabled_ids() -> list[str]:
    """Ids of plugins that are on by default. Used to resolve the effective enabled
    set for a conversation whose ``config.enabled_plugins`` is **absent** (a legacy
    conversation created before plugins) — an explicit ``[]`` still means none."""
    return [p.id for p in PLUGIN_REGISTRY.values() if p.default_enabled]


def effective_enabled_ids(config: dict) -> list[str]:
    """The plugin ids enabled for a conversation. A missing ``enabled_plugins`` key
    falls back to the default-on set (so default plugins reach legacy conversations);
    an explicit list (including ``[]``) is honored verbatim."""
    enabled = (config or {}).get("enabled_plugins")
    return list(enabled) if isinstance(enabled, list) else default_enabled_ids()


def _import_plugin_modules() -> None:
    """Import every plugin package so its register() calls have run."""
    for mod in _PLUGIN_MODULES:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            # A plugin package may not exist yet (e.g. before Summarizer lands).
            continue


def seed_plugins() -> None:
    """Import plugin packages and run each plugin's ``seed_prompts``. Idempotent;
    best-effort per plugin (one plugin's bad seed never blocks the others)."""
    _import_plugin_modules()
    for plugin in PLUGIN_REGISTRY.values():
        if plugin.seed_prompts is not None:
            try:
                plugin.seed_prompts()
            except Exception as exc:  # noqa: BLE001 — seeding must not block startup
                print(f"plugin {plugin.id!r} seed_prompts skipped: {exc}")
