"""Lenient structured-output parsing for chain LLM steps.

Local GGUF models (Gemma et al.) emit JSON that is *mostly* right but often
wrapped in ```json fences, prefixed with chatter, or trailed by prose. This
generalizes prattletale's deterministic-repair idea into an app-agnostic
``parse_json_output`` used by Tomeberry's Track/Develop modes (and anyone else
that needs JSON out of a model that won't reliably produce it).

The contract: never raise. Return ``(obj, error)`` — ``obj`` is the parsed value
(or ``None`` on failure), ``error`` is a human-readable reason (or ``None`` on
success). Callers record the raw + error and degrade gracefully.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_balanced(text: str) -> Optional[str]:
    """Return the first balanced ``{...}`` or ``[...]`` span, ignoring braces
    inside strings. Handles leading/trailing prose around the JSON body."""
    start = None
    opener = closer = ""
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            opener = ch
            closer = "}" if ch == "{" else "]"
            break
    if start is None:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _validate(obj: Any, schema: Optional[dict]) -> Optional[str]:
    """A *very* light shape check (top-level type + required keys for objects).

    Not a full JSON-Schema validator — just enough to catch a model returning the
    wrong top-level shape. Returns an error string or None.
    """
    if not schema:
        return None
    expected = schema.get("type")
    if expected == "object" and not isinstance(obj, dict):
        return f"expected object, got {type(obj).__name__}"
    if expected == "array" and not isinstance(obj, list):
        return f"expected array, got {type(obj).__name__}"
    if expected == "object":
        missing = [k for k in (schema.get("required") or []) if k not in obj]
        if missing:
            return f"missing required keys: {', '.join(missing)}"
    return None


def parse_json_output(
    raw: str, schema: Optional[dict] = None
) -> tuple[Optional[Any], Optional[str]]:
    """Parse model output into JSON leniently. Returns ``(obj, error)``.

    Tries, in order: direct ``json.loads``; fenced-block extraction; first
    balanced ``{...}``/``[...]`` span. On success runs a light ``schema`` shape
    check. Never raises.
    """
    if not raw or not raw.strip():
        return None, "empty output"

    candidates: list[str] = []
    stripped = raw.strip()
    candidates.append(stripped)
    fenced = _strip_fences(raw)
    if fenced and fenced != stripped:
        candidates.append(fenced)
    balanced = _extract_balanced(fenced or stripped)
    if balanced:
        candidates.append(balanced)

    last_err = "no JSON found"
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except (ValueError, TypeError) as exc:
            last_err = str(exc)
            continue
        shape_err = _validate(obj, schema)
        if shape_err:
            last_err = shape_err
            continue
        return obj, None
    return None, last_err
