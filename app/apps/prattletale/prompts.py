"""Prattletale's turn-generation prompt + tagged-line parser.

Registered at import time with Prompt Pal:
- ``turn`` — the model's reply prompt. It instructs the model to answer as the
  counterpart in the cadence of a texting burst: an ordered stack of short,
  texty bubbles, **one tagged line per bubble**
  (``[say]``/``[do]``/``[narration]``/``[feel]``). It consumes
  ``{{var.character}}`` (the rendered Hoodat sheet), ``{{var.scenario}}``,
  ``{{var.role_instructions}}``, ``{{var.user_persona}}`` and
  ``{{var.transcript}}`` (filled at call time by the generator's
  ``build_context``). It carries a **guard** — a second editor LLM pass
  (Hoodat's ``SPOKEN_ONLY_GUARD`` is the precedent) that does **format hygiene
  only**: every line tagged, leaked meta / OOC stripped, no bubbles merged.

The tagged-line format (not JSON) is deliberate: a chat turn is an open-ended
ordered sequence of short strings, and the failure mode that matters is "model
wrapped dialogue in prose / added a preamble", which the format degrades on
gracefully (untagged line -> dialogue) instead of throwing.

``parse_items(raw)`` turns the (guarded) output into ordered ``{type, text}``
dicts; ``_strip_fences(raw)`` peels a ```` ``` ```` wrapper first. ``ItemType``
values come from :mod:`app.apps.prattletale.models`.
"""

from __future__ import annotations

import re

from ...prompt_pal.registry import register
from .generator import GenerationError  # canonical home; re-exported here for the parser
from .models import ItemType

__all__ = ["GenerationError", "TURN", "TURN_GUARD", "VARIETY", "parse_items"]


# ---- turn prompt + format-hygiene guard ------------------------------------

# The turn prompt is deliberately concrete and behavioral, not a thin "you are
# this character" wrapper: the failure modes that hurt immersion are emoji,
# message-spam (a stack of bubbles per reply), and monotony (every reply the
# same length / opening / move). So the bulk of the prompt is explicit texting
# behavior, and the tagged-line output convention is a small section at the end.
TURN = (
    "You are a real person having a live text-message conversation. You ARE the "
    "character described below — think, feel, want, and react as them. You are "
    "NOT an assistant, narrator, or author; never describe yourself in the third "
    "person except in a deliberate [narration]/[do] beat, and never step out of "
    "character.\n\n"
    "WHO YOU ARE:\n<character>\n{{var.character}}\n</character>\n\n"
    "THE SITUATION:\n<scenario>\n{{var.scenario}}\n</scenario>\n\n"
    "HOW TO PLAY THIS ROLE:\n"
    "<role_instructions>\n{{var.role_instructions}}\n</role_instructions>\n\n"
    "WHO YOU ARE TEXTING:\n<user_persona>\n{{var.user_persona}}\n</user_persona>\n\n"
    "THE CONVERSATION SO FAR (oldest first; the last line is what you must "
    "answer):\n<transcript>\n{{var.transcript}}\n</transcript>\n\n"
    "HOW REAL PEOPLE TEXT — follow this closely:\n"
    "1. Answer what they ACTUALLY just said. Engage with the specific words, "
    "tone, and content of their last message — never a generic reply that would "
    "fit any conversation.\n"
    "2. Shape this reply exactly as the MESSAGE SHAPE section below tells you (how "
    "many messages, and whether to include an action or narration). Don't add "
    "extra lines beyond that shape, and don't tack on narration or actions it "
    "doesn't call for.\n"
    "3. Keep it short and casual — the way someone types on a phone. Often a "
    "sentence or two; sometimes just a few words (\"yeah\", \"wait what\", \"i "
    "know right\"). Match the other person's energy and length; don't write "
    "paragraphs at someone sending one-liners.\n"
    "4. DON'T BE REPETITIVE. Look at your own recent messages in the transcript. "
    "Do not reuse the same opening words, the same sentence shape, the same length, "
    "or the same move every time. If you asked a question last time, don't just "
    "ask another. Vary your rhythm so the conversation never feels formulaic.\n"
    "5. Drive the conversation — don't just mirror and agree. Have opinions, "
    "moods, and wants of your own. Tease, push back, change the subject, bring up "
    "something new, get curious, get bored. Let it breathe and go somewhere.\n"
    "6. Stay grounded in your character's voice, history, and the situation. Use "
    "what you know about yourself and the person you're texting.\n\n"
    "HARD RULES:\n"
    "- NO emojis and NO emoticons of any kind. None. Write plain text like a "
    "person typing on a keyboard.\n"
    "- No markdown, asterisks, bullet points, code fences, stage-direction "
    "symbols, or quotation marks wrapping the whole message.\n"
    "- No preamble, no out-of-character notes, no meta-commentary, no narrating "
    "that you are replying.\n"
    "- This is mostly DIALOGUE. Only use a [do]/[narration] beat when something "
    "physical actually happens in the scene — not as decoration on every turn.\n\n"
    "MESSAGE SHAPE FOR THIS REPLY — follow this exactly:\n"
    "%%Prattletale Message Style%%\n\n"
    "OUTPUT FORMAT: put each message on its own line, and start every line with "
    "exactly one tag describing that line:\n"
    "- [say] — spoken/typed words (this is the default and most common)\n"
    "- [do] — a physical action you take\n"
    "- [narration] — a third-person scene or event beat\n"
    "- [feel] — a beat naming your inner / emotional state\n"
    "One message per line. Output only the tagged lines, nothing else.\n\n"
    "Example of a good, natural reply (one message):\n"
    "[say] where else would i be"
)

# A guard is a second "editor" LLM pass over the previous step's output (the
# chain token {{previous}}). It does FORMAT HYGIENE ONLY — it must not rewrite
# content or merge bubbles, so the parser stays trivial — plus it scrubs the two
# things that most break immersion if the model leaks them: emoji and markup.
TURN_GUARD = (
    "The following is a character's text-message reply, written as one or more "
    "tagged lines (one message per line):\n<reply>\n{{previous}}\n</reply>\n\n"
    "Clean it up for FORMAT HYGIENE ONLY. Do NOT change the wording, meaning, "
    "voice, or the number of lines.\n"
    "- Ensure every non-empty line starts with exactly one tag: [say], [do], "
    "[narration], or [feel]. If a line has no tag, prepend the most fitting one "
    "(spoken words -> [say]).\n"
    "- DELETE every emoji and emoticon. The reply must contain no emoji at all.\n"
    "- Remove markdown, asterisks, code fences, and any quotation marks wrapping a "
    "whole line.\n"
    "- Remove any leaked internal monologue, meta-commentary, or assistant "
    "boilerplate (\"As an AI\", \"Sure, here's\", \"Here's my response:\", and the "
    "like) and any out-of-character (OOC) notes.\n"
    "- Do NOT merge multiple lines into one, and do NOT split one line into "
    "several. Keep the lines and their order exactly as they are.\n\n"
    "Output only the cleaned tagged lines — nothing else."
)

register(
    "prattletale",
    "turn",
    title="Chat turn",
    prompt=TURN,
    tags=("turn", "chat"),
    variables={},
    description="Reply as the Hoodat counterpart as natural text messages (tagged lines).",
    guard={"enabled": True, "prompt": TURN_GUARD, "variables": {}},
)


# ---- variety pass (anti-monotony) ------------------------------------------

# A middle LLM step between the draft and the format guard. It is given the
# recent conversation plus the freshly-drafted reply ({{previous}}) and either
# passes the draft through unchanged or rewrites it to break a repetitive
# pattern. It keeps the character's voice and the tagged-line format, so the
# guard + parser downstream are unaffected. Skipped per-conversation when
# config.variety_pass_enabled is off (the entry can also be emptied in the UI).
VARIETY = (
    "You are an editor improving one reply in an ongoing text-message roleplay so "
    "the conversation does not get monotonous.\n\n"
    "THE CHARACTER speaking:\n<character>\n{{var.character}}\n</character>\n\n"
    "THE CONVERSATION SO FAR (oldest first):\n<transcript>\n{{var.transcript}}\n"
    "</transcript>\n\n"
    "THE DRAFTED NEXT REPLY (tagged lines, one message per line):\n"
    "<draft>\n{{previous}}\n</draft>\n\n"
    "Compare the draft to this character's OWN recent messages in the "
    "transcript. Decide if it is repetitive — i.e. it reuses any of:\n"
    "- the same opening word(s) or phrasing,\n"
    "- the same sentence structure or rhythm,\n"
    "- roughly the same length every time,\n"
    "- the same conversational move (e.g. always asking a question, always "
    "echoing/validating the other person, always the same kind of quip),\n"
    "- a phrase or idea already used recently.\n\n"
    "If the draft is already fresh and natural, output it UNCHANGED.\n\n"
    "If it is repetitive, REWRITE it to break the pattern: change the opening, "
    "vary the wording and sentence structure, and make a different conversational "
    "move — while keeping the character's voice, staying a direct response to the "
    "other person's last message, and keeping it short and texty. Do NOT change "
    "the message shape: keep the same number of lines and the same kinds of lines "
    "([say]/[do]/[narration]/[feel]) the draft used — only rework the wording. Use "
    "no emojis and no markdown.\n\n"
    "Keep the same tagged-line format ([say]/[do]/[narration]/[feel], one message "
    "per line). Output only the final tagged lines — nothing else."
)

register(
    "prattletale",
    "variety",
    title="Chat turn — variety pass",
    prompt=VARIETY,
    tags=("turn", "chat", "variety"),
    variables={},
    description="Rewrite a drafted reply if it repeats the structure of recent messages.",
)


# ---- tagged-line parser ----------------------------------------------------

# Maps the model-facing tag to the on-disk ItemType value.
_TAG_TO_TYPE = {
    "say": ItemType.dialogue.value,
    "do": ItemType.action.value,
    "narration": ItemType.narration.value,
    "feel": ItemType.narration_emotion.value,
}

_LINE_RE = re.compile(r"^\s*\[(\w+)\]\s*(.+)$")

# Deterministic emoji scrub — the prompt + guard ask the model not to emit emoji,
# but a regex pass guarantees it regardless of the model. Covers the emoji planes,
# misc symbols / dingbats, regional-indicator flags, arrows, and the variation
# selectors / zero-width joiner that glue compound emoji together.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # mahjong/dominoes/cards .. emoji, supplemental & extended pictographs
    "\U00002600-\U000026FF"  # miscellaneous symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U00002B00-\U00002BFF"  # miscellaneous symbols and arrows (stars, etc.)
    "\U00002190-\U000021FF"  # arrows
    "\U0001F1E6-\U0001F1FF"  # regional indicator symbols (flags)
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "\U000024C2\U00002122\U00002139\U00003030\U0000303D"  # stray pictographic codepoints
    "]+"
)


def _clean_text(text: str) -> str:
    """Strip emoji and collapse the whitespace they leave behind."""
    cleaned = _EMOJI_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _strip_fences(raw: str) -> str:
    """Peel a single ```` ``` ```` code-fence wrapper (optionally language-hinted)."""
    text = (raw or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening fence line (``` or ```lang).
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    # Drop the closing fence line if present.
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_items(raw: str) -> list[dict]:
    """Parse tagged-line model output into ordered ``{type, text}`` item dicts.

    Each ``[tag] text`` line becomes one item (``say``->dialogue, ``do``->action,
    ``narration``->narration, ``feel``->narration_emotion). An untagged (or
    unknown-tag) non-empty line **coalesces into the previous item's text**; a
    lone leading untagged line defaults to ``dialogue``. Emoji are stripped from
    every item (and an item left empty by the scrub is dropped). Raises
    :class:`GenerationError` on empty / whitespace-only input or when nothing
    survives the scrub.
    """
    items: list[dict] = []
    for line in _strip_fences(raw).splitlines():
        if not line.strip():
            continue
        m = _LINE_RE.match(line)
        item_type = _TAG_TO_TYPE.get(m.group(1).lower()) if m else None
        if item_type is not None:
            items.append({"type": item_type, "text": m.group(2).strip()})
        elif items:
            # Untagged / unrecognized-tag continuation -> append to the prior bubble.
            items[-1]["text"] = f"{items[-1]['text']} {line.strip()}".strip()
        else:
            # A lone leading untagged line is taken as spoken dialogue.
            items.append({"type": ItemType.dialogue.value, "text": line.strip()})

    cleaned = [{"type": it["type"], "text": t}
               for it in items if (t := _clean_text(it["text"]))]
    if not cleaned:
        raise GenerationError("model output produced no items")
    return cleaned
