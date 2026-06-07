"""Deterministic-first repair of a raw model turn.

The chat pipeline used to run an unconditional LLM "guard" pass over every reply
for format hygiene — an extra round-trip that could also quietly normalize voice
away or undo a standing order. This replaces it with a cheap, deterministic
Python cleanup (:func:`repair_output_deterministic`) run before
:func:`app.apps.prattletale.prompts.parse_items`; only when the deterministic
pass + parser still can't produce items does the caller fall back to an LLM
repair step (``generator.run_repair`` over the ``repair`` prompt).

The deterministic pass never raises — ``parse_items`` stays the single arbiter of
"is this usable" — and never rewrites wording: it strips code fences, scrubs
emoji, drops empty lines, removes obvious assistant preambles, and caps a runaway
wall of text. It reuses the regexes the parser already owns
(``prompts._strip_fences``, ``prompts._EMOJI_RE``) so the two passes agree.
"""

from __future__ import annotations

import re

# Max bubbles a single reply may carry; anything past this is a runaway and the
# tail is dropped (the director plan caps at ~4, so this is a generous backstop).
_MAX_LINES = 20

# A leading line that is obvious assistant/meta boilerplate rather than an in-
# character bubble (only stripped from the TOP of the reply, and only when it is
# not itself a tagged/quoted/asterisk message line — see _looks_like_content).
_PREAMBLE_RE = re.compile(
    r"^\s*(sure|okay|ok|certainly|of course|here(?:'s| is| are)|as an ai|"
    r"as a language model|response|reply|assistant|output)\b[^a-z0-9]*.*?[:\-]?\s*$",
    re.IGNORECASE,
)

# A line that is clearly a real message (tagged, fully quoted, or all-asterisk
# action) and so must never be mistaken for a preamble.
_CONTENT_HINT_RE = re.compile(r'^\s*(\[\w+\]|".*"|\*.*\*)')


def _looks_like_content(line: str) -> bool:
    return bool(_CONTENT_HINT_RE.match(line))


def repair_output_deterministic(raw: str) -> str:
    """Clean a raw model turn for FORMAT only (never wording). Returns the cleaned
    text; ``parse_items`` remains the arbiter, so this never raises."""
    from .prompts import _EMOJI_RE, _strip_fences

    text = _strip_fences(raw or "")
    lines = [ln.rstrip() for ln in text.splitlines()]

    # Drop leading assistant/meta preamble lines (only from the top, and only when
    # the line isn't itself a real message).
    while lines:
        head = lines[0].strip()
        if not head:
            lines.pop(0)
            continue
        if _PREAMBLE_RE.match(head) and not _looks_like_content(head):
            lines.pop(0)
            continue
        break

    cleaned: list[str] = []
    for ln in lines:
        scrubbed = _EMOJI_RE.sub("", ln)
        scrubbed = re.sub(r"[ \t]{2,}", " ", scrubbed).strip()
        if scrubbed:
            cleaned.append(scrubbed)

    if len(cleaned) > _MAX_LINES:
        cleaned = cleaned[:_MAX_LINES]
    return "\n".join(cleaned)
