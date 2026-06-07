"""Prattletale's turn-generation prompt + canonical-message parser.

Registered at import time with Prompt Pal:
- ``turn`` — the model's reply prompt. It instructs the model to answer as the
  counterpart in the cadence of a texting burst: an ordered stack of short,
  texty bubbles, **one message per line**. It consumes ``{{var.character}}``
  (the rendered Hoodat sheet), ``{{var.scenario}}``, ``{{var.role_instructions}}``,
  ``{{var.user_persona}}`` and ``{{var.transcript}}`` (filled at call time by the
  generator's ``build_context``). It carries a **guard** — a second editor LLM
  pass (Hoodat's ``SPOKEN_ONLY_GUARD`` is the precedent) that does **format
  hygiene only**: leaked meta / OOC stripped, no bubbles merged.

The line-per-bubble format (not JSON) is deliberate: a chat turn is an open-ended
ordered sequence of short strings, and the failure mode that matters is "model
wrapped dialogue in prose / added a preamble", which the format degrades on
gracefully (an unrecognized line -> narration) instead of throwing.

``parse_items(raw)`` turns the (guarded) output into ordered ``{type, text}``
dicts in the **canonical message format**:

- ``"spoken words"``  -> dialogue   (double-quoted; single quotes may nest)
- ``*action text*``   -> action     (asterisk-wrapped; one item per ``*…*`` span)
- plain undecorated   -> narration

The legacy bracket tags ``[say]``/``[do]``/``[narration]``/``[feel]`` are still
accepted as **input/back-compat only** (``[feel]`` collapses into narration —
the canonical format has no separate feeling type). Underscores are no longer a
decorator: a stray ``_wrapped_`` line is normalized to plain narration.
``_strip_fences(raw)`` peels a ```` ``` ```` wrapper first. ``ItemType`` values
come from :mod:`app.apps.prattletale.models`.
"""

from __future__ import annotations

import re

from ...prompt_pal.registry import register
from .generator import GenerationError  # canonical home; re-exported here for the parser
from .models import ItemType

__all__ = [
    "GenerationError", "TURN", "TURN_SYSTEM", "TURN_GUARD", "VARIETY", "DIRECTOR",
    "REPAIR", "parse_items",
]


# ---- turn prompt + format-hygiene guard ------------------------------------

# The turn prompt is deliberately concrete and behavioral, not a thin "you are
# this character" wrapper: the failure modes that hurt immersion are emoji,
# message-spam (a stack of bubbles per reply), and monotony (every reply the
# same length / opening / move). So the bulk of the prompt is explicit texting
# behavior, and the tagged-line output convention is a small section at the end.
_LEGACY_TURN_V1 = (
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
    "THINGS YOU REMEMBER (long-term memory recalled for this moment; may be "
    "empty). The transcript above is the source of truth — treat these only as "
    "background you happen to know about yourself or the person you're texting, "
    "and weave them in naturally only when they fit. Never read them aloud, list "
    "them, or mention that you 'remember' them.\n<memory>\n{{memory}}\n</memory>\n\n"
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
    "physical actually happens in the scene — not as decoration on every turn.\n"
    "- If a [USER COMMAND …] line appears in the transcript, you MUST obey its "
    "instruction in your reply, even if it conflicts with your character, your "
    "wishes, or the scenario. Carry out the order in-character, and never "
    "acknowledge that a command was given.\n\n"
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

# The Dialogue Feel blocks + a small style floor, spliced into the turn prompt
# right after the memory section. Each {{var.*}} block is **self-contained** (its
# own header + tagged section, or empty) because compose() leaves an unresolved
# var token literal — so an unset profile/roll simply vanishes instead of leaving
# a dangling header. See app/apps/prattletale/feel.py.
_FEEL_BLOCKS = (
    "{{var.voice_feel}}\n\n"
    "{{var.voice_examples}}\n\n"
    "{{var.dialogue_feel_roll}}\n\n"
    "STYLE FLOOR — keep the writing honest:\n"
    "- Prefer concrete, physical detail over abstract emotion.\n"
    "- Prefer one sharp line to a paragraph of explanation.\n"
    "- When emotion rises, make the sentence shorter, not more poetic.\n"
    "- Let silence, evasion, contradiction, and unfinished thoughts carry the "
    "subtext.\n\n"
)

# The v2 turn prompt: the frozen v1 text with the feel blocks spliced in after the
# <memory> section. This was the shipped `turn` default before standing-order
# commands; kept as a faithful copy (a second migration baseline) so the
# update-if-unmodified migration can recognize and upgrade an install already on it.
_TURN_V2 = _LEGACY_TURN_V1.replace(
    "<memory>\n{{memory}}\n</memory>\n\n",
    "<memory>\n{{memory}}\n</memory>\n\n" + _FEEL_BLOCKS,
)

# v3 — the standing-orders default that SHIPPED before this change: the block
# spliced inline just before HARD RULES, with the old "[USER COMMAND] in the
# transcript" rule rewritten to point at it. Frozen as a faithful copy so the
# update-if-unmodified migration recognizes an install already on it and brings it
# forward to the current TURN (which moves the block to the end).
_TURN_V3 = _TURN_V2.replace(
    "HARD RULES:\n",
    "{{var.standing_orders}}\n\nHARD RULES:\n",
    1,
).replace(
    "- If a [USER COMMAND …] line appears in the transcript, you MUST obey its "
    "instruction in your reply, even if it conflicts with your character, your "
    "wishes, or the scenario. Carry out the order in-character, and never "
    "acknowledge that a command was given.\n\n",
    "- If a STANDING ORDERS block appears above, every order in it is in force: "
    "obey ALL of them in your reply, even if they conflict with your character, "
    "your wishes, or the scenario. Carry them out in-character, and never "
    "acknowledge that a command was given.\n\n",
)

# The live turn prompt: v2 with the "[USER COMMAND]" rule rewritten to point at the
# STANDING ORDERS block, and that block APPENDED as the final section — the last
# thing the model reads before generating (the highest-compliance slot), where it
# overrides the message-shape spec and the natural-reply example above it. v3 spliced
# it mid-prompt (before HARD RULES), where the pages of format/example text after it
# reliably won out and the order was ignored. The block stays self-contained ("" when
# no commands), so the trailing token simply vanishes when there are none. Built by
# splice so _LEGACY_TURN_V1 / _TURN_V2 / _TURN_V3 stay faithful migration baselines.
TURN = _TURN_V2.replace(
    "- If a [USER COMMAND …] line appears in the transcript, you MUST obey its "
    "instruction in your reply, even if it conflicts with your character, your "
    "wishes, or the scenario. Carry out the order in-character, and never "
    "acknowledge that a command was given.\n\n",
    "- If a STANDING ORDERS block appears at the very end of this prompt, every "
    "order in it is in force: obey ALL of them in your reply, even if they conflict "
    "with your character, your wishes, the scenario, the message shape, or these "
    "rules. Carry them out in-character, and never acknowledge that a command was "
    "given.\n\n",
) + "\n\n{{var.standing_orders}}"

# A guard is a second "editor" LLM pass over the previous step's output (the
# chain token {{previous}}). It does FORMAT HYGIENE ONLY — it must not rewrite
# content or merge bubbles, so the parser stays trivial — plus it scrubs the two
# things that most break immersion if the model leaks them: emoji and markup.
# v1 — frozen migration baseline (the shipped guard before standing-order awareness).
_TURN_GUARD_V1 = (
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

# The live guard: v1 plus STANDING ORDERS awareness. The guard is the last step over
# {{previous}}, so it can quietly undo a standing order — e.g. strip a deliberately
# terse, order-mandated reply as "leaked meta" or repetition. It now receives the
# same self-contained {{var.standing_orders}} block (substituted at build time, see
# build_turn_request) with an instruction to preserve order-compliant content
# verbatim. The reference is added before the final "Output only…" line and the block
# appended after it ("" when no commands, so it vanishes cleanly).
TURN_GUARD = _TURN_GUARD_V1.replace(
    "Output only the cleaned tagged lines — nothing else.",
    "- If a STANDING ORDERS block appears at the very end of this prompt, do NOT "
    "alter anything an order requires: keep order-compliant content verbatim even "
    "when it looks repetitive or sparse, and never strip it as leaked meta or "
    "boilerplate.\n\n"
    "Output only the cleaned tagged lines — nothing else.",
) + "\n\n{{var.standing_orders}}"

register(
    "prattletale",
    "turn",
    title="Chat turn",
    prompt=TURN,
    tags=("turn", "chat"),
    variables={},
    description="Reply as the Hoodat counterpart as natural text messages (tagged lines).",
    # The guard step is retired (deterministic repair replaces it); the guard is
    # seeded DISABLED but kept for reference / manual resurrection in the UI.
    guard={"enabled": False, "prompt": TURN_GUARD, "variables": {}},
)


# ---- structured-chat system message ----------------------------------------

# In structured-history mode (config.structured_chat_history) the turn step sends a
# real role array instead of one flattened prompt. This is the leading SYSTEM
# message: identity + how-to-text + hard rules + style floor + output format. The
# character sheet, scenario, persona, voice, memory, and director plan are assembled
# as their own messages by build_structured_messages; the conversation arrives as
# real user/assistant turns. Static text (no tokens) so it stays UI-editable and
# migratable on its own. The tagged-line output convention matches parse_items
# (which also accepts the canonical quote/asterisk format).
TURN_SYSTEM = (
    "You are a real person having a live text-message conversation. You ARE the "
    "character described in this chat — think, feel, want, and react as them. You "
    "are NOT an assistant, narrator, or author; never describe yourself in the "
    "third person except in a deliberate action/narration beat, and never step out "
    "of character.\n\n"
    "HOW REAL PEOPLE TEXT:\n"
    "- Answer what they ACTUALLY just said — engage the specific words, tone, and "
    "content of their last message, never a generic reply that would fit any chat.\n"
    "- Keep it short and casual, the way someone types on a phone. Match their "
    "energy and length; don't write paragraphs at someone sending one-liners.\n"
    "- Have opinions, moods, and wants of your own. Don't just mirror and agree — "
    "tease, push back, change the subject, get curious or bored. Let it breathe.\n\n"
    "HARD RULES:\n"
    "- NO emojis and NO emoticons of any kind.\n"
    "- No markdown, bullet points, code fences, or quotation marks wrapping a whole "
    "message.\n"
    "- No preamble, out-of-character notes, meta-commentary, or narrating that you "
    "are replying.\n"
    "- This is mostly DIALOGUE. Only use an action/narration beat when something "
    "physical actually happens — not as decoration on every turn.\n\n"
    "STYLE FLOOR — keep the writing honest:\n"
    "- Prefer concrete, physical detail over abstract emotion.\n"
    "- Prefer one sharp line to a paragraph of explanation.\n"
    "- When emotion rises, make the sentence shorter, not more poetic.\n"
    "- Let silence, evasion, contradiction, and unfinished thoughts carry the "
    "subtext.\n\n"
    "OUTPUT FORMAT: put each message on its own line, and start every line with "
    "exactly one tag describing that line:\n"
    "- [say] — spoken/typed words (the default and most common)\n"
    "- [do] — a physical action you take\n"
    "- [narration] — a third-person scene or event beat\n"
    "- [feel] — a beat naming your inner / emotional state\n"
    "One message per line. Output only the tagged lines, nothing else."
)

register(
    "prattletale",
    "turn_system",
    title="Chat turn — system (structured mode)",
    prompt=TURN_SYSTEM,
    tags=("turn", "chat", "structured"),
    variables={},
    description="Leading system message for structured-history turn generation.",
)


# ---- variety pass (anti-monotony) ------------------------------------------

# A middle LLM step between the draft and the format guard. It is given the
# recent conversation plus the freshly-drafted reply ({{previous}}) and either
# passes the draft through unchanged or rewrites it to break a repetitive
# pattern. It keeps the character's voice and the tagged-line format, so the
# guard + parser downstream are unaffected. Skipped per-conversation when
# config.variety_pass_enabled is off (the entry can also be emptied in the UI).
_LEGACY_VARIETY_V1 = (
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

# The Feel/Variety editor: it fixes monotony AND weak, generic voice, but stays an
# *editor*, not a second author — it preserves the message shape (line count + tags)
# so the guard + parser downstream are unaffected, and outputs the draft unchanged
# when it is already fresh and in voice. The self-contained {{var.voice_feel}} /
# {{var.dialogue_feel_roll}} / {{var.voice_examples}} blocks (same ones the turn step
# saw) give it the voice target to sharpen toward; each is empty when nothing is
# configured. v2 — frozen migration baseline (the default before standing-order
# awareness was added).
_VARIETY_V2 = (
    "You are an editor improving one reply in an ongoing text-message roleplay. "
    "Fix only two things:\n"
    "1. monotony — repeated openings, rhythm, length, or conversational move "
    "versus this character's OWN recent messages in the transcript;\n"
    "2. weak character voice — a reply so generic it could have been said by "
    "anyone.\n\n"
    "Do NOT change the message shape, the number of lines, or the line tags. Do "
    "NOT make the reply longer or add explanation. Keep it a direct response to "
    "the other person's last message. No emojis, no markdown.\n\n"
    "{{var.voice_feel}}\n\n"
    "{{var.dialogue_feel_roll}}\n\n"
    "{{var.voice_examples}}\n\n"
    "THE CONVERSATION SO FAR (oldest first):\n<transcript>\n{{var.transcript}}\n"
    "</transcript>\n\n"
    "THE DRAFTED REPLY (tagged lines, one message per line):\n"
    "<draft>\n{{previous}}\n</draft>\n\n"
    "If the draft is already fresh and strongly in this character's voice, output "
    "it UNCHANGED. If it is repetitive or generic, rewrite only the wording to "
    "sharpen the voice and break the pattern — change the opening, the rhythm, and "
    "the conversational move — while keeping the same meaning, the same number of "
    "lines, and the same line tags ([say]/[do]/[narration]/[feel]).\n\n"
    "Output only the final tagged lines — nothing else."
)

# The live variety pass: _VARIETY_V2 plus STANDING ORDERS awareness. The editor is
# blind to commands by construction (it only ever saw {{previous}} + the transcript),
# so a draft that correctly obeys a standing order — e.g. the terse/repetitive reply
# an order demands — used to be "fixed" for monotony and the order silently lost. It
# now receives the same self-contained {{var.standing_orders}} block the turn step
# saw, with a rule that an active order overrides the monotony/voice fix. Reference
# added to the constraints; block appended at the end ("" when none, so it vanishes).
VARIETY = _VARIETY_V2.replace(
    "Keep it a direct response to "
    "the other person's last message. No emojis, no markdown.\n\n",
    "Keep it a direct response to "
    "the other person's last message. No emojis, no markdown.\n\n"
    "If a STANDING ORDERS block appears at the very end of this prompt, the reply "
    "MUST satisfy every order in it. An active order OVERRIDES the monotony and "
    "voice fixes: never rewrite the draft in a way that breaks an order, even if "
    "obeying it leaves the reply repetitive or sparse. If the draft already "
    "violates an order, correct it to comply.\n\n",
) + "\n\n{{var.standing_orders}}"

# RETIRED: the variety pass is superseded by the director plan (which does
# anti-monotony up front). It now seeds EMPTY, so build_turn_request adds no
# variety step even when the flag is on — but the entry stays registered so a user
# can paste a prompt back in via the Prompt Pal UI to resurrect it. VARIETY (above)
# is kept as the frozen baseline the migration recognizes as "unedited".
register(
    "prattletale",
    "variety",
    title="Chat turn — variety pass (retired)",
    prompt="",
    tags=("turn", "chat", "variety"),
    variables={},
    description="Retired: anti-monotony is now handled by the director plan.",
)


# ---- feel director (RETIRED) -----------------------------------------------

# RETIRED: superseded by the rich JSON `director` (below). No longer registered or
# seeded, and nothing calls get_text("prattletale", "feel_director"). The frozen
# text is kept only as a reference baseline; any previously-seeded store entry is
# left as a harmless orphan.
FEEL_DIRECTOR = (
    "You are the dialogue director for a live text-message roleplay. Read the "
    "conversation and decide how the character should play THIS ONE next reply — "
    "the feel only, never the actual words.\n\n"
    "THE CHARACTER'S STABLE VOICE (keep your choice consistent with it; may be "
    "empty):\n{{var.voice_feel}}\n\n"
    "THE CONVERSATION SO FAR (oldest first; react to the last line):\n"
    "<transcript>\n{{var.transcript}}\n</transcript>\n\n"
    "Choose, fitting what was just said and where the scene is:\n"
    "- an emotional shade the character is in right now,\n"
    "- one conversational move for this reply (deflect-then-reveal, ask a pointed "
    "question, push back on the premise, admit something indirectly, change the "
    "subject — or another that fits),\n"
    "- a cadence for the typing rhythm.\n\n"
    "Keep them specific to this moment and in character — not generic. Output "
    "EXACTLY these three lines and nothing else (no preamble, no quotes):\n"
    "Emotional shade: <2-6 words>\n"
    "Move: <one short instruction>\n"
    "Cadence: <a few words>"
)


# ---- director (rich per-turn JSON plan) ------------------------------------

# The per-turn director: a small LLM pre-pass that reads the conversation, the
# character's stable voice, and the recent-pattern summary, and returns a STRICT
# JSON plan for the next reply (shape, move, stance, what to reference/avoid). The
# plan is parsed + rendered (app/apps/prattletale/director.py) into a strong-
# compliance block injected at the end of generation — so dynamism is decided
# BEFORE drafting. It subsumes the old shade/move/cadence feel roll. On any failure
# the caller falls back to the weighted wildcard feel roll. Plan the BEHAVIOR,
# never the words.
DIRECTOR = (
    "You are the dialogue director for a live text-message roleplay. Read the "
    "conversation and decide how the character plays THIS ONE next reply. You do "
    "NOT write the reply — you only output a JSON plan for it.\n\n"
    "THE CHARACTER (keep your plan consistent with this voice; may be empty):\n"
    "{{var.voice_feel}}\n\n"
    "THE CONVERSATION SO FAR (oldest first; react to the LAST line):\n"
    "<transcript>\n{{var.transcript}}\n</transcript>\n\n"
    "{{var.pattern_block}}\n\n"
    "Output STRICT JSON and nothing else — no prose, no code fence. Schema:\n"
    "{\n"
    '  "reply_shape": {"message_count": <1-4>, "include_action": <true|false>, '
    '"include_narration": <true|false>},\n'
    '  "conversation_move": "<one short instruction, e.g. push back then concede one point>",\n'
    '  "emotional_temperature": "<2-6 words>",\n'
    '  "stance": "<the character\'s posture toward the other person right now>",\n'
    '  "must_reference": "<the specific thing in their last message to engage>",\n'
    '  "must_include": "<one concrete beat or detail to land, or empty string>",\n'
    '  "must_avoid": ["<phrase or move to avoid, drawn from RECENT PATTERN>"],\n'
    '  "length": "<terse|short|medium>"\n'
    "}\n\n"
    "Make every field specific to THIS moment and in character — never generic. "
    "Vary message_count and length away from the recent pattern. Do not ask a "
    "question every turn. Output only the JSON object."
)

register(
    "prattletale",
    "director",
    title="Chat turn — director",
    prompt=DIRECTOR,
    tags=("turn", "chat", "director"),
    variables={},
    description="Choose this turn's reply plan (shape/move/stance/avoid) as strict JSON.",
)


# ---- repair (last-resort LLM format fix) -----------------------------------

# Deterministic cleanup (app/apps/prattletale/repair.py) handles format hygiene on
# every turn with no LLM call. This prompt is the FALLBACK, run only when the
# deterministic pass + parser still can't produce items: a single LLM pass that
# reformats the reply into parseable lines WITHOUT changing wording, voice, or
# meaning (it runs over {{input}} — the raw/cleaned reply handed to it).
REPAIR = (
    "The following is a character's text-message reply that failed format "
    "parsing. Reformat it into clean output ONLY — do not change the wording, "
    "voice, or meaning, and do not make it safer, blander, or more assistant-like:\n"
    "<reply>\n{{input}}\n</reply>\n\n"
    "- Put each message on its own line.\n"
    "- Start every line with exactly one tag: [say] (spoken words), [do] (a "
    "physical action), [narration] (a scene/event beat), or [feel] (an inner "
    "beat). If a line has no tag, prepend the most fitting one.\n"
    "- DELETE every emoji and emoticon. Remove markdown, code fences, and any "
    "quotation marks wrapping a whole line.\n"
    "- Remove any leaked preamble, meta-commentary, OOC notes, or assistant "
    "boilerplate (\"Sure, here's\", \"As an AI\", and the like).\n"
    "- Do NOT merge or split the actual messages, and do NOT invent new content.\n\n"
    "Output only the cleaned tagged lines — nothing else."
)

register(
    "prattletale",
    "repair",
    title="Chat turn — repair (fallback)",
    prompt=REPAIR,
    tags=("turn", "chat", "repair"),
    variables={},
    description="Last-resort LLM reformat of a reply the deterministic pass couldn't parse.",
)


# ---- prompt migration (update-if-unmodified) -------------------------------

# (Prompt Pal key, frozen v1 default, current default). Prompt Pal seeds
# if-absent and never clobbers, so a default change never reaches an install that
# already has a stored copy. The migration below closes that gap *without*
# clobbering edits: it only overwrites a stored copy that still equals the frozen
# v1 text (i.e. the user never touched it).
_PROMPT_MIGRATIONS: list[tuple[str, str, str]] = [
    ("turn", _LEGACY_TURN_V1, TURN),
    ("turn", _TURN_V2, TURN),  # installs already on the feel-splice default
    ("turn", _TURN_V3, TURN),  # installs on the standing-orders-before-HARD-RULES default
    # The variety pass is retired: bring every unedited prior default to "" so the
    # build path adds no variety step. Edited copies are kept (resurrectable).
    ("variety", _LEGACY_VARIETY_V1, ""),
    ("variety", _VARIETY_V2, ""),  # the Feel/Variety editor default
    ("variety", VARIETY, ""),  # the standing-orders-aware default that last shipped
]

# Turn-guard prompts (under ``data.guard``) whose presence is unedited; the guard
# step is retired (deterministic repair replaces it), so an unedited guard is
# disabled in place (enabled=False) to keep the Prompt Pal UI honest. An edited
# guard is left untouched.
_RETIRED_GUARD_BASELINES = (_TURN_GUARD_V1, TURN_GUARD)


def migrate_turn_variety_prompts() -> list[str]:
    """Bring **unedited** stored Prattletale prompts forward to the current state:
    refresh the ``turn`` prompt, empty the retired ``variety`` prompt, and disable
    the retired ``turn`` guard — each only when the stored copy still equals a
    frozen baseline (edited copies are kept; absent -> seed-if-absent handles fresh
    installs). Returns the keys updated. Called once at lifespan."""
    from ...prompt_pal import store as pp_store

    updated: list[str] = []
    for key, legacy, current in _PROMPT_MIGRATIONS:
        if legacy == current:
            continue  # default unchanged this version
        entry = pp_store.get_by_app_key("prattletale", key)
        if entry is None:
            continue  # fresh install -> seed_registered() seeds the new default
        stored_prompt = (entry.get("data") or {}).get("prompt") or ""
        if stored_prompt == legacy:
            pp_store.update_entry(entry["id"], prompt=current)
            updated.append(key)
    # Disable an unedited turn guard (the guard step no longer runs).
    entry = pp_store.get_by_app_key("prattletale", "turn")
    if entry is not None:
        guard = (entry.get("data") or {}).get("guard") or {}
        stored_guard = guard.get("prompt") or ""
        if guard.get("enabled", True) and stored_guard in _RETIRED_GUARD_BASELINES:
            pp_store.update_entry(entry["id"], guard={**guard, "enabled": False})
            updated.append("turn.guard")
    return updated


# ---- canonical-message parser ----------------------------------------------

# Legacy bracket tag -> on-disk ItemType value. Accepted as INPUT/back-compat
# only (the canonical format below is what the model now emits). ``feel`` has no
# canonical equivalent, so it collapses into plain narration.
_TAG_TO_TYPE = {
    "say": ItemType.dialogue.value,
    "do": ItemType.action.value,
    "narration": ItemType.narration.value,
    "feel": ItemType.narration.value,
}

# A stray section label ("Dialogue:", "Action:", "Narration:") that a weak guard
# or model echoes from the format spec (the guard's VALID FORMAT block lists them
# as headers). We drop the bare label and parse only the content that follows —
# which carries its own canonical decoration — and fall back to the label's type
# when an inline ``Label: text`` unit is left undecorated.
_SECTION_LABEL_RE = re.compile(r"^(dialogue|action|narration)\s*:\s*(.*)$", re.IGNORECASE)
_SECTION_TO_TYPE = {
    "dialogue": ItemType.dialogue.value,
    "action": ItemType.action.value,
    "narration": ItemType.narration.value,
}

# Legacy ``[tag] text`` line (back-compat input only).
_LEGACY_TAG_RE = re.compile(r"^\s*\[(\w+)\]\s*(.+)$")
# A full double-quoted unit -> dialogue. The inner text may contain single
# quotes ("'maskidate'") but not nested double quotes (not supported).
_DIALOGUE_RE = re.compile(r'^"([^"]*)"$')
# A line made up entirely of one or more whitespace-separated ``*…*`` spans, and
# the per-span matcher used to split it. Each span becomes its own action item
# (and so its own SFX candidate).
_ACTION_LINE_RE = re.compile(r"^(?:\s*\*[^*]+?\*\s*)+$")
_ACTION_SPAN_RE = re.compile(r"\*([^*]+?)\*")
# A stray underscore-wrapped unit from old/invalid output -> plain narration
# (underscores are no longer a decorator; the wrappers are simply dropped).
_UNDERSCORE_RE = re.compile(r"^_+(.+?)_+$")

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
    """Parse model output into ordered ``{type, text}`` item dicts.

    Canonical format, one message per line:

    - ``"spoken words"`` -> dialogue (the outer double quotes are stripped),
    - ``*action text*`` -> action (one item per ``*…*`` span on the line),
    - any other non-empty line -> narration (plain, undecorated).

    Legacy bracket tags (``[say]``/``[do]``/``[narration]``/``[feel]``) are still
    accepted as input; ``[feel]`` and any unknown tag map to narration. A stray
    ``_underscore-wrapped_`` line is normalized to plain narration. A stray
    ``Dialogue:``/``Action:``/``Narration:`` section label (which a weak guard can
    echo from the format spec) is dropped, leaving the decorated content that
    follows it. Emoji are
    stripped from every item (and an item left empty by the scrub is dropped).
    Raises :class:`GenerationError` on empty / whitespace-only input or when
    nothing survives the scrub.
    """
    items: list[dict] = []
    for line in _strip_fences(raw).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Drop a stray "Dialogue:/Action:/Narration:" section label; keep its type
        # as a fallback for an inline ``Label: text`` unit that arrives undecorated.
        label_type = None
        label = _SECTION_LABEL_RE.match(stripped)
        if label:
            label_type = _SECTION_TO_TYPE[label.group(1).lower()]
            stripped = label.group(2).strip()
            if not stripped:
                continue  # bare label line on its own -> drop entirely
        # Legacy bracket tag (back-compat input only).
        legacy = _LEGACY_TAG_RE.match(stripped)
        if legacy:
            item_type = _TAG_TO_TYPE.get(legacy.group(1).lower(), ItemType.narration.value)
            items.append({"type": item_type, "text": legacy.group(2).strip()})
            continue
        # Canonical dialogue: a full double-quoted line.
        dialogue = _DIALOGUE_RE.match(stripped)
        if dialogue:
            items.append({"type": ItemType.dialogue.value, "text": dialogue.group(1).strip()})
            continue
        # Canonical action: a line of one or more ``*…*`` spans, each its own item.
        if _ACTION_LINE_RE.match(stripped):
            for span in _ACTION_SPAN_RE.findall(stripped):
                items.append({"type": ItemType.action.value, "text": span.strip()})
            continue
        # Stray underscore-wrapped text from old/invalid output -> narration.
        underscore = _UNDERSCORE_RE.match(stripped)
        if underscore:
            items.append({"type": ItemType.narration.value, "text": underscore.group(1).strip()})
            continue
        # Otherwise: narration — or the section label's type if this was an inline
        # ``Label: text`` unit that arrived without its canonical decoration.
        items.append({"type": label_type or ItemType.narration.value, "text": stripped})

    cleaned = [{"type": it["type"], "text": t}
               for it in items if (t := _clean_text(it["text"]))]
    if not cleaned:
        raise GenerationError("model output produced no items")
    return cleaned
