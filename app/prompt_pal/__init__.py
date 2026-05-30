"""Prompt Pal — the project-wide registry for internal app prompts.

Whenever an app needs "creative input" from the LLM it uses a *prompt*. Prompt
Pal gives every such prompt an editable, filterable, deep-linkable home so they
can be tweaked over time, while keeping a code-side default so a fresh checkout
(or a test with no seeded store) still works.

- ``compose`` — the resolution primitive (``{prompt, variables}`` → text).
- ``registry.register`` — apps declare their prompt set in code at import time.
- ``registry.seed_registered`` — writes any missing registered prompt to the
  store (seed-if-absent); called once at app startup.
- ``service.get_text(app, key)`` — what app code calls; store copy wins, else
  the in-code default.
- ``store`` — file-per-doc persistence at ``config/prompt_pal/<id>.json``.
"""

from __future__ import annotations

from .compose import (  # noqa: F401
    PromptCompositionError,
    PromptNode,
    PromptStore,
    compose,
)
from .registry import register, seed_registered  # noqa: F401
from .service import get_text, id_for  # noqa: F401
