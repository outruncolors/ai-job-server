"""Prattletale turn director — parse + render the per-turn JSON plan.

The director is a small LLM pre-pass (run as its own tiny job in
:func:`generator.run_director`) that reads the conversation, the character's
stable voice, and the recent-pattern summary, and returns a **plan** for the
next reply: how many messages, the conversational move, stance, emotional
temperature, what to reference / include / avoid, and a length band. The plan is
rendered into a strong-compliance block injected at the very end of generation,
so dynamism is decided *before* drafting (not patched in by a cleanup pass).

This module is pure: :func:`parse_director_plan` validates/normalizes the LLM's
JSON (returning ``None`` when nothing usable parsed, so the caller falls back to
the wildcard feel roll), and :func:`render_director_plan` renders a validated
plan into the prompt block (``""`` for a falsy plan, so the
``{{var.dialogue_feel_roll}}`` slot simply vanishes — same self-contained-block
convention as :mod:`app.apps.prattletale.feel`). The plan **subsumes** the old
shade/move/cadence feel roll: ``emotional_temperature`` is the shade,
``conversation_move`` the move, ``length`` the cadence.
"""

from __future__ import annotations

import json
from typing import Optional

_LENGTHS = ("terse", "short", "medium")


def _extract_json_object(raw: str) -> Optional[str]:
    """Return the first balanced ``{...}`` substring of ``raw`` (tolerating code
    fences and surrounding prose), or ``None`` when there is no balanced object.
    Brace counting is string-aware so a ``}`` inside a JSON string never closes
    the object early."""
    text = (raw or "").strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _as_str(value) -> str:
    return str(value).strip() if value is not None else ""


def parse_director_plan(raw: str) -> Optional[dict]:
    """Parse the director LLM's output into a normalized plan dict, or ``None``
    when nothing usable parsed (the caller then falls back to the wildcard feel
    roll). Every field is coerced/clamped so downstream rendering is total."""
    blob = _extract_json_object(raw)
    if blob is None:
        return None
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    shape = data.get("reply_shape") or {}
    if not isinstance(shape, dict):
        shape = {}
    try:
        message_count = int(shape.get("message_count", 1))
    except (TypeError, ValueError):
        message_count = 1
    message_count = max(1, min(4, message_count))

    length = _as_str(data.get("length")).lower()
    if length not in _LENGTHS:
        length = "short"

    must_avoid_raw = data.get("must_avoid") or []
    if isinstance(must_avoid_raw, str):
        must_avoid_raw = [must_avoid_raw]
    must_avoid = [s for s in (_as_str(x) for x in must_avoid_raw) if s]

    plan = {
        "reply_shape": {
            "message_count": message_count,
            "include_action": bool(shape.get("include_action", False)),
            "include_narration": bool(shape.get("include_narration", False)),
        },
        "conversation_move": _as_str(data.get("conversation_move")),
        "emotional_temperature": _as_str(data.get("emotional_temperature")),
        "stance": _as_str(data.get("stance")),
        "must_reference": _as_str(data.get("must_reference")),
        "must_include": _as_str(data.get("must_include")),
        "must_avoid": must_avoid,
        "length": length,
    }
    # A plan with no directive content at all is treated as "nothing usable" so the
    # caller falls back rather than injecting an empty shell.
    if not any([
        plan["conversation_move"], plan["emotional_temperature"], plan["stance"],
        plan["must_reference"], plan["must_include"], plan["must_avoid"],
    ]):
        return None
    return plan


def render_director_plan(plan: Optional[dict]) -> str:
    """Render a validated plan into the strong-compliance prompt block, or ``""``
    for a falsy plan (so the slot vanishes — same convention as the feel blocks).
    Slots in for the per-turn feel roll: it carries shade/move/cadence and more."""
    if not plan:
        return ""
    shape = plan.get("reply_shape") or {}
    lines: list[str] = []
    mc = shape.get("message_count", 1)
    lines.append(
        f"Send {mc} message(s). "
        f"Include an action beat: {'yes' if shape.get('include_action') else 'no'}. "
        f"Include narration: {'yes' if shape.get('include_narration') else 'no'}."
    )
    if plan.get("conversation_move"):
        lines.append(f"Conversational move: {plan['conversation_move']}.")
    temp, stance = plan.get("emotional_temperature"), plan.get("stance")
    if temp:
        lines.append(f"Emotional temperature: {temp}.")
    if stance:
        lines.append(f"Stance: {stance}.")
    if plan.get("must_reference"):
        lines.append(f"Engage specifically with: {plan['must_reference']}.")
    if plan.get("must_include"):
        lines.append(f"Make sure this lands: {plan['must_include']}.")
    if plan.get("must_avoid"):
        lines.append("Do NOT do any of these: " + "; ".join(plan["must_avoid"]) + ".")
    if plan.get("length"):
        lines.append(f"Length: {plan['length']}.")
    body = "\n".join(lines)
    return (
        "PLAN FOR THIS REPLY — follow it exactly without mentioning it:\n"
        f"<reply_plan>\n{body}\n</reply_plan>"
    )
