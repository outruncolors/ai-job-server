"""Composable prompt resolution primitive (not a UI).

A *prompt* is JSON: ``{"prompt": "<text with {{var.NAME}}>", "variables": {...}}``.
``compose(node)`` renders it to a string. A variable value may be:

- a literal string (used as-is),
- another prompt object (resolved recursively first, its output piped in), or
- a stored-prompt reference ``{"prompt_id": "<id>"}`` (looked up via ``store``).

Composition recurses until the full text is built; ``max_depth`` guards cycles.

This is **stage-1** resolution and is always non-final: only in-scope
``{{var.NAME}}`` tokens are substituted. The new-namespace tokens (``{{wc.NAME}}`` /
``{{ctx.NAME}}``), the chain tokens (``{{input}}`` / ``{{previous}}`` / …) and any
``{{var.NAME}}`` with no matching variable are all left intact — and crucially the
var literal-fallback never fires here — so the **stage-2** resolver
(``app.prompt_template.render(..., final=True)`` at execution) still sees them and a
parent compose or the chain's own variables can still fill them. We reuse that
module's tokenizer for the pass.

This module is shared infrastructure under ``app/prompt_pal/`` — Prompt Pal is
the project-wide registry for the internal LLM prompts apps use. It was promoted
here verbatim from ``app/apps/blaboratory/prompt_compose.py`` (which now re-exports
it for back-compat).
"""

from __future__ import annotations

from typing import Callable, Optional, Union

from ..prompt_template import _TOKEN_RE

PromptNode = Union[str, dict]
PromptStore = Callable[[str], Optional[PromptNode]]


class PromptCompositionError(Exception):
    """Raised on malformed nodes, missing stored prompts, or over-deep recursion."""


def compose(
    node: PromptNode,
    *,
    store: Optional[PromptStore] = None,
    depth: int = 0,
    max_depth: int = 16,
) -> str:
    """Resolve a prompt node to its final text. See module docstring."""
    if depth > max_depth:
        raise PromptCompositionError(f"composition exceeded max depth {max_depth}")

    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        raise PromptCompositionError(f"cannot compose node of type {type(node).__name__}")

    if "prompt_id" in node:
        if store is None:
            raise PromptCompositionError("prompt_id reference but no store provided")
        ref = store(node["prompt_id"])
        if ref is None:
            raise PromptCompositionError(f"stored prompt not found: {node['prompt_id']!r}")
        return compose(ref, store=store, depth=depth + 1, max_depth=max_depth)

    if "prompt" not in node:
        raise PromptCompositionError("prompt node missing 'prompt' key")

    text = node["prompt"]
    variables = node.get("variables") or {}
    resolved = {
        name: compose(value, store=store, depth=depth + 1, max_depth=max_depth)
        for name, value in variables.items()
    }

    def _sub(m) -> str:
        token = m.group(1).strip()
        if token.startswith("var."):
            key = token[4:]
            if key in resolved:
                return resolved[key]
        return m.group(0)  # leave chain tokens / unresolved vars intact

    return _TOKEN_RE.sub(_sub, text)
