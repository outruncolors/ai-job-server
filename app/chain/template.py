"""Back-compat shim. The templating engine now lives in :mod:`app.prompt_template`
(shared by chain, Prompt Pal, Prattletale, and the generation surfaces). This module
re-exports the public API so existing ``from ..template import render_template`` imports
keep working.
"""

from __future__ import annotations

from app.prompt_template import (  # noqa: F401
    _TOKEN_RE,
    RenderResult,
    Substitution,
    render,
    render_template,
)

__all__ = ["_TOKEN_RE", "RenderResult", "Substitution", "render", "render_template"]
