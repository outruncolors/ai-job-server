"""Back-compat shim. The composable-prompt primitive moved to the shared
``app/prompt_pal/compose.py`` when Prompt Pal (the project-wide prompt registry)
generalized it. This module re-exports it so existing imports keep working.
"""

from __future__ import annotations

from ...prompt_pal.compose import (  # noqa: F401
    PromptCompositionError,
    PromptNode,
    PromptStore,
    compose,
)
