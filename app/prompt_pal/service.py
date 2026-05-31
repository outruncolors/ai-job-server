"""High-level prompt resolution — what app code calls.

``get_text(app, key)`` returns the fully-composed prompt text for a logical
``(app, key)``. The **store copy wins** (so user edits in the Prompt Pal UI take
effect), falling back to the **in-code registered default** when the store has no
file (fresh checkout / test with an empty store). Composition resolves
``{{var.NAME}}`` and any ``{"prompt_id": ...}`` references via the store, while
leaving chain tokens (``{{input}}`` / ``{{previous}}``) for the chain executor.
"""

from __future__ import annotations

from typing import Optional

from . import registry, store
from .compose import compose


class UnknownPromptError(KeyError):
    """Raised when no stored entry and no registered default exist for (app, key)."""


def _node_for(app: str, key: str) -> Optional[dict]:
    """The compose node for ``(app, key)``: store copy if present, else the
    registered in-code default. None if neither exists.
    """
    entry = store.get_by_app_key(app, key)
    if entry is not None:
        d = entry.get("data") or {}
        return {"prompt": d.get("prompt", ""), "variables": d.get("variables") or {}}

    rp = registry.get_registered(app, key)
    if rp is None:
        # The owning app's prompts module may not have been imported yet.
        registry._import_prompt_modules()
        rp = registry.get_registered(app, key)
    return rp.as_node() if rp is not None else None


def _guard_for(app: str, key: str) -> Optional[dict]:
    """The raw guard dict ``{enabled, prompt, variables}`` for ``(app, key)``:
    store copy first (user edits win), else the registered in-code default. None
    if there is no guard. Mirrors ``_node_for``'s store-then-registry order.
    """
    entry = store.get_by_app_key(app, key)
    if entry is not None:
        return (entry.get("data") or {}).get("guard")

    rp = registry.get_registered(app, key)
    if rp is None:
        registry._import_prompt_modules()
        rp = registry.get_registered(app, key)
    return rp.guard if rp is not None else None


def get_text(app: str, key: str, *, variables: Optional[dict] = None) -> str:
    """Resolve ``(app, key)`` to composed prompt text.

    ``variables`` overlays/extends the node's own variables (used e.g. by Hoodat
    to inject ``{{var.character}}`` / ``{{var.detail}}`` at call time).
    """
    node = _node_for(app, key)
    if node is None:
        raise UnknownPromptError(f"no prompt registered or stored for ({app!r}, {key!r})")
    if variables:
        node = {"prompt": node["prompt"], "variables": {**node.get("variables", {}), **variables}}
    return compose(node, store=store.node_for_id)


def get_guard(app: str, key: str, *, variables: Optional[dict] = None) -> Optional[str]:
    """Resolve the composed guard prompt text for ``(app, key)``, or None when
    there is no guard / it is disabled / its prompt is empty.

    The guard text typically references ``{{previous}}`` — the original prompt's
    output — which the chain executor fills when the guard runs as the second
    LLM step. ``variables`` overlays the guard node's own variables (same as
    ``get_text``).
    """
    guard = _guard_for(app, key)
    if not guard or not guard.get("enabled", True):
        return None
    prompt = guard.get("prompt") or ""
    if not prompt.strip():
        return None
    node = {"prompt": prompt, "variables": {**(guard.get("variables") or {}), **(variables or {})}}
    return compose(node, store=store.node_for_id)


def id_for(app: str, key: str) -> Optional[str]:
    """The stored entry ``id`` for ``(app, key)`` (for ``?highlight=`` links), or
    None if the prompt has not been seeded to the store yet.
    """
    entry = store.get_by_app_key(app, key)
    return entry.get("id") if entry is not None else None
