from __future__ import annotations

import re
from typing import Optional

_TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def render_template(
    template: str,
    *,
    input: str = "",
    previous: str = "",
    context: str = "",
    step_index: int = 0,
    step_name: str = "",
    step_inputs: Optional[dict[int, list[str]]] = None,
    step_outputs: Optional[dict[int, list[str]]] = None,
    variables: Optional[dict[str, str]] = None,
    extra: Optional[dict[str, str]] = None,
) -> str:
    """Substitute {{token}} expressions in `template`.

    Supported tokens:
      - {{input}}            initial chain input
      - {{previous}}         last LLM step's text_output
      - {{context}}          resolved context items
      - {{step_index}}       current step's 1-based index
      - {{step_name}}        current step's display name
      - {{N_input}}          rendered prompt fed to step number N (last invocation)
      - {{N_output}}         text output of step number N (last invocation)
      - {{var.NAME}}         caller-provided variable, falling back to its default
      - extra tokens         any key in `extra` (e.g. {{memory}} from a step's
                             memory-retrieval config) resolves to its value
    Unknown tokens render as empty strings.
    """
    step_inputs = step_inputs or {}
    step_outputs = step_outputs or {}
    variables = variables or {}
    extra = extra or {}

    def _last(values: list[str]) -> str:
        return values[-1] if values else ""

    def _resolve(token: str) -> str:
        if token == "input":
            return input
        if token == "previous":
            return previous
        if token == "context":
            return context
        if token == "step_index":
            return str(step_index)
        if token == "step_name":
            return step_name
        if token.startswith("var."):
            return variables.get(token[4:], "")
        if token in extra:
            return extra[token]
        m = re.fullmatch(r"(\d+)_(input|output)", token)
        if m:
            n = int(m.group(1))
            if m.group(2) == "input":
                return _last(step_inputs.get(n, []))
            return _last(step_outputs.get(n, []))
        return ""

    return _TOKEN_RE.sub(lambda m: _resolve(m.group(1)), template)
