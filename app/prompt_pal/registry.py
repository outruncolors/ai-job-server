"""In-code registration table for Prompt Pal.

Apps declare their prompt set in code at import time via ``register(...)``. At
startup, ``seed_registered()`` writes any **missing** ``(app, key)`` to the store
(seed-if-absent — it never clobbers a user's edits). The in-code defaults also
serve as the fallback ``service.get_text`` uses when the store has no file yet
(fresh checkout, or a test with an empty store dir).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Optional

from . import store
from .compose import PromptNode

# Modules that call register() at import time. seed_registered() imports these
# so registration is guaranteed to have run regardless of import order.
_PROMPT_MODULES = (
    "app.apps.blaboratory.prompts",
    "app.apps.hoodat.prompts",
)


@dataclass(frozen=True)
class RegisteredPrompt:
    app: str
    key: str
    title: str
    prompt: str
    description: str = ""
    tags: tuple[str, ...] = ()
    variables: dict[str, Any] = field(default_factory=dict)
    # Optional in-code guard default ({enabled, prompt, variables}); seeded
    # alongside the main prompt so a code-declared guard appears in the UI.
    guard: Optional[dict] = None

    def as_node(self) -> PromptNode:
        return {"prompt": self.prompt, "variables": dict(self.variables)}

    def as_fields(self) -> dict:
        fields: dict = {
            "app": self.app,
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "prompt": self.prompt,
            "variables": dict(self.variables),
        }
        if self.guard is not None:
            fields["guard"] = dict(self.guard)
        return fields


_REGISTRY: dict[tuple[str, str], RegisteredPrompt] = {}


def register(
    app: str,
    key: str,
    *,
    title: str,
    prompt: str,
    description: str = "",
    tags: tuple[str, ...] = (),
    variables: Optional[dict[str, Any]] = None,
    guard: Optional[dict] = None,
) -> RegisteredPrompt:
    """Declare an app prompt. Idempotent on re-import (last declaration wins).

    ``guard`` is an optional editor-pass default ``{enabled, prompt, variables}``
    seeded with the prompt (see ``GuardSpec``).
    """
    rp = RegisteredPrompt(
        app=app,
        key=key,
        title=title,
        prompt=prompt,
        description=description,
        tags=tuple(tags),
        variables=dict(variables or {}),
        guard=dict(guard) if guard is not None else None,
    )
    _REGISTRY[(app, key)] = rp
    return rp


def get_registered(app: str, key: str) -> Optional[RegisteredPrompt]:
    return _REGISTRY.get((app, key))


def registered_entries() -> list[RegisteredPrompt]:
    return list(_REGISTRY.values())


def _import_prompt_modules() -> None:
    """Import every app prompt module so its register() calls have run."""
    for mod in _PROMPT_MODULES:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            # An app may not exist yet (e.g. before Hoodat lands).
            continue


def seed_registered() -> None:
    """Write any registered prompt missing from the store. Seed-if-absent;
    never overwrites an existing (possibly user-edited) entry. Idempotent.

    One narrow exception: if a registered prompt declares a ``guard`` but the
    stored entry predates the guard feature (its JSON has no ``guard`` key at
    all), backfill the code-declared guard. A user who *disabled* a guard keeps a
    ``guard`` object on disk (``enabled: false``), so this never clobbers an
    intentional choice — it only upgrades legacy, never-had-a-guard entries.
    """
    _import_prompt_modules()
    for rp in _REGISTRY.values():
        existing = store.get_by_app_key(rp.app, rp.key)
        if existing is None:
            store.create_entry(rp.as_fields())
        elif rp.guard is not None and "guard" not in existing:
            store.update_entry(existing["id"], guard=dict(rp.guard))
