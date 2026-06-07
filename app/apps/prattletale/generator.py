"""Prattletale turn-generation pipeline — the chain executor run synchronously.

Mirrors Hoodat's ``_run_single_step``/``run_create`` and Blaboratory's
direct-executor pattern: drives :func:`app.chain.executor.execute_chain_job`
**directly** (not via the shared ``JobQueue``, so a foreground reply never
starves real jobs), scaffolding an on-disk job for debuggability.

The pipeline is split into discrete, independently testable stages:

- :func:`build_context` — **pure** (store reads only): flatten the recent
  transcript window + render the counterpart sheet into the prompt's variable
  bundle.
- :func:`build_turn_request` — the two-step ``[turn, guard]`` chain (the
  narrative-editor guard is a second ``llm`` step over ``{{previous}}``; skipped
  when the prompt has no guard).
- :func:`run_model_turn` — load → build → execute → parse → persist + trace; on
  **any** failure it appends a ``system_error`` turn and returns it (the router
  renders an inline error bubble), never raising to the caller.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ...chain.executor import execute_chain_job
from ...chain.models import (
    Alternative,
    ChainJobRequest,
    ChainLLMConfig,
    ChainStep,
    MemoryStepConfig,
)
from ...jobs import create_job, find_job_dir
from ...llm_config import get_default_as_chain_llm_config
from ...prompt_pal.service import get_text
from ...wildcards import resolve_wildcards
from ..hoodat.characters_store import get_character
from ..hoodat.prompts import render_character_context
from . import store
from .director import parse_director_plan, render_director_plan
from .feel import (
    render_voice_examples,
    render_voice_feel,
    resolve_dialogue_feel_roll,
)
from .models import Author, ItemType
from .voice import reveal_schedule, synthesize_turn

JOB_TYPE = "prattletale_turn"
# The director pre-pass and the (conditional) repair pass each run as their own
# tiny one-step job (reuses the full LLM plumbing: endpoint resolution, model
# swap, on-disk trace).
JOB_TYPE_DIRECTOR = "prattletale_director"
JOB_TYPE_REPAIR = "prattletale_repair"

# Bumped when the prompt/pipeline shape changes; surfaced in the per-turn trace and
# the /debug/prompts endpoint so it's never ambiguous which pipeline produced a
# reply. "core-1" = director + structured messages + deterministic-first repair.
PRATTLETALE_PROMPT_VERSION = "core-1"

# Rendered when the device user has no persona, so the prompt's <user_persona>
# section never collapses to a dangling label with empty contents.
_EMPTY_PERSONA = "(No specific persona — an ordinary conversational partner.)"


class GenerationError(Exception):
    """Raised when a turn cannot produce a usable reply. The canonical home for
    this exception (SP2's parser re-imports it from here)."""


# ---- LLM resolution --------------------------------------------------------

# Roomy generation cap for the chat-turn pipeline so long replies (and the
# guard pass) aren't truncated by the 2048 default. Raised, never lowered.
_MIN_TURN_MAX_TOKENS = 6144


def _resolve_llm(llm: Optional[ChainLLMConfig]) -> ChainLLMConfig:
    if llm is None:
        try:
            llm = get_default_as_chain_llm_config()
        except RuntimeError as exc:
            raise GenerationError(str(exc)) from exc
    # Reasoning is controlled per chain step (see _llm_step's `thinking`); the
    # whole chat-turn pipeline runs no-thinking. Give replies a roomy token cap.
    if llm.max_tokens < _MIN_TURN_MAX_TOKENS:
        llm = llm.model_copy(update={"max_tokens": _MIN_TURN_MAX_TOKENS})
    return llm


def _llm_step(
    number: int, step_id: str, name: str, prompt: str = "", *,
    memory: Optional[dict] = None, thinking: Optional[bool] = None,
    messages: Optional[list[dict]] = None,
) -> ChainStep:
    """Build a single-alternative ``llm`` step. When ``memory`` is given, the
    alternative carries a :class:`MemoryStepConfig` so the executor retrieves a
    memory block and exposes it via the ``{{memory}}`` token (and writes
    ``steps/NNN_<id>/memory.txt`` for the trace). When ``messages`` is given the
    step sends that role array (structured-history mode) instead of the single
    ``prompt``. ``thinking`` overrides the project reasoning default (None =
    default-on; False for the in-character reply, which roleplay best practice runs
    without a reasoning trace)."""
    alt = Alternative(
        prompt=prompt,
        messages=messages,
        memory=MemoryStepConfig(**memory) if memory else None,
        thinking=thinking,
    )
    return ChainStep(
        number=number, id=step_id, name=name, type="llm",
        alternatives=[alt],
    )


# ---- context assembly (pure) -----------------------------------------------

def _render_item(item: dict) -> str:
    """Render one item for the transcript script: dialogue (and a ``summary``
    recap) as plain text, every other (visible) type as a parenthesized stage
    direction. ``command`` items are NOT rendered here — a command is a standing
    order (a switch the user flipped on, not a line of conversation), gathered
    separately by :func:`_collect_standing_orders` and injected as its own prompt
    block. They are excluded from the transcript script entirely."""
    text = (item.get("text") or "").strip()
    if not text:
        return ""
    if item.get("type") in (ItemType.dialogue.value, ItemType.summary.value):
        return text
    return f"({text})"


def _speaker_label(author: str, character: dict) -> str:
    if author == Author.model.value:
        return (character.get("name") or "").strip() or "Counterpart"
    if author == Author.system.value:
        return "Summary"
    return "User"


def _flatten_transcript(turns: list[dict], character: dict) -> str:
    """Flatten turns to a ``[Speaker] …`` script, skipping ``hidden_from_context``,
    ``system_error``, and ``command`` items (commands are standing orders, injected
    as their own block — see :func:`_collect_standing_orders`). A turn with no
    visible items is dropped entirely (no dangling speaker label)."""
    lines: list[str] = []
    for turn in turns:
        visible = [
            it for it in (turn.get("items") or [])
            if not it.get("hidden_from_context")
            and it.get("type") != ItemType.system_error.value
            and it.get("type") != ItemType.command.value
            # OOC side messages are a parallel channel the character never sees —
            # gathered for the OOC pipeline (render_ooc_history), excluded here.
            and it.get("type") != ItemType.ooc.value
        ]
        rendered = [r for r in (_render_item(it) for it in visible) if r]
        if not rendered:
            continue
        # A summary turn carries history forward under a distinct label so the
        # model reads it as "what happened earlier", not as a spoken message.
        if turn.get("author") == Author.system.value:
            lines.append(f"[Summary so far] {' '.join(rendered)}")
        else:
            lines.append(f"[{_speaker_label(turn.get('author'), character)}] {' '.join(rendered)}")
    return "\n".join(lines)


def _transcript_to_messages(turns: list[dict], character: dict) -> list[dict]:
    """Walk turns into real chat **role messages** (the structured-history path),
    applying the SAME skip rules as :func:`_flatten_transcript` (drop
    ``hidden_from_context``, ``system_error``, ``command``, ``ooc``; a turn with no
    visible items is dropped). Role mapping:

    - user turn  -> ``{"role": "user", "content": …}``
    - model turn -> ``{"role": "assistant", "content": …}``
    - summary turn (system author) -> ``{"role": "system", "content": "[Earlier] …"}``

    Item rendering reuses :func:`_render_item` (dialogue/summary as plain text,
    other visible types as parenthesized stage directions), joined per turn.
    """
    messages: list[dict] = []
    for turn in turns:
        visible = [
            it for it in (turn.get("items") or [])
            if not it.get("hidden_from_context")
            and it.get("type") != ItemType.system_error.value
            and it.get("type") != ItemType.command.value
            and it.get("type") != ItemType.ooc.value
        ]
        rendered = [r for r in (_render_item(it) for it in visible) if r]
        if not rendered:
            continue
        content = " ".join(rendered)
        author = turn.get("author")
        if author == Author.system.value:
            messages.append({"role": "system", "content": f"[Earlier] {content}"})
        elif author == Author.model.value:
            messages.append({"role": "assistant", "content": content})
        else:
            messages.append({"role": "user", "content": content})
    return messages


def _collect_standing_orders(turns: list[dict]) -> list[str]:
    """The text of every **active** (non-hidden) ``command`` item across the whole
    transcript, oldest first. A command is a standing order — a switch the user
    flipped on that stays in force for every future reply until they hide or delete
    it — so it is gathered from the entire transcript, never windowed: an order set
    twenty turns ago must not fall out of scope. Hiding/deleting the command item
    (the manager modal) is what switches it back off."""
    orders: list[str] = []
    for turn in turns:
        for it in (turn.get("items") or []):
            if it.get("type") != ItemType.command.value or it.get("hidden_from_context"):
                continue
            text = (it.get("text") or "").strip()
            if text:
                orders.append(text)
    return orders


def _render_standing_orders(orders: list[str]) -> str:
    """Render active commands as a self-contained STANDING ORDERS block, or ``""``
    when there are none. Self-contained (its own header) so the ``{{var.standing_orders}}``
    token simply vanishes when empty — same convention as the Dialogue Feel blocks."""
    if not orders:
        return ""
    lines = "\n".join(f"- {order}" for order in orders)
    return (
        "STANDING ORDERS — out-of-character instructions the user has switched on. "
        "They stay in force for THIS reply and every future reply until switched "
        "off. You MUST obey every one, even if it conflicts with your character, "
        "your wishes, or the scenario. Carry them out in-character, and never "
        "acknowledge that a command was given:\n"
        f"{lines}"
    )


def render_ooc_history(turns: list[dict]) -> str:
    """Flatten every ``ooc`` item across the **whole** transcript (not windowed,
    oldest first) into a ``[You] …`` / ``[Author] …`` back-and-forth script — the
    OOC pipeline's side channel. Spans all OOC sessions so a new out-of-character
    exchange always carries the earlier ones forward. ``""`` when no OOC has
    happened yet (the ``{{var.ooc_history}}`` token then simply vanishes).

    The user side is labeled ``[You]``; the author-behind-the-character side
    ``[Author]`` (this OOC reply speaks as the author, not the character).
    ``hidden_from_context`` OOC items are skipped (they still render, with the
    hidden tag, but aren't fed to generation — same as hidden in-character items)."""
    lines: list[str] = []
    for turn in turns:
        for it in (turn.get("items") or []):
            if it.get("type") != ItemType.ooc.value or it.get("hidden_from_context"):
                continue
            text = (it.get("text") or "").strip()
            if not text:
                continue
            label = "You" if it.get("author") == Author.user.value else "Author"
            lines.append(f"[{label}] {text}")
    return "\n".join(lines)


def _latest_user_text(turns: list[dict]) -> str:
    """The most recent user turn's visible text — the strongest memory-retrieval
    signal (what they *just* said). Empty when the user hasn't spoken yet."""
    for turn in reversed(turns):
        if turn.get("author") != Author.user.value:
            continue
        visible = [
            it for it in (turn.get("items") or [])
            if not it.get("hidden_from_context")
            and it.get("type") != ItemType.system_error.value
            # A command is an instruction, not "what the user said" — skip it so
            # retrieval falls back to the prior real utterance / the whole window.
            and it.get("type") != ItemType.command.value
            # An OOC aside isn't part of the in-character conversation — skip it so
            # memory retrieval is never driven by an out-of-character line.
            and it.get("type") != ItemType.ooc.value
        ]
        text = " ".join(r for r in (_render_item(it) for it in visible) if r).strip()
        if text:
            return text
    return ""


# ---- recent-pattern analysis (pure; feeds the director only) ----------------

# Trivial openers ignored when collecting "recent openings" — they carry no
# structural signal worth varying. Lowercased, punctuation-stripped.
_PATTERN_STOP_OPENERS = {"i", "the", "a", "an", "and", "but", "so", "oh", "ok", "okay"}
_WORD_RE = re.compile(r"[a-z0-9']+")


def _model_dialogue_items(turn: dict) -> list[str]:
    """Visible dialogue texts of a model turn, in order (empty for non-model or
    item-less turns). Mirrors the context skip rules: system_error excluded."""
    if turn.get("author") != Author.model.value:
        return []
    out: list[str] = []
    for it in (turn.get("items") or []):
        if it.get("hidden_from_context"):
            continue
        if it.get("type") != ItemType.dialogue.value:
            continue
        text = (it.get("text") or "").strip()
        if text:
            out.append(text)
    return out


def _visible_model_item_count(turn: dict) -> int:
    """How many visible (non-error, non-hidden) items a model turn committed."""
    if turn.get("author") != Author.model.value:
        return 0
    return sum(
        1 for it in (turn.get("items") or [])
        if not it.get("hidden_from_context")
        and it.get("type") != ItemType.system_error.value
    )


def build_recent_pattern_summary(
    transcript: dict, character: dict, *, lookback: int = 6
) -> dict:
    """Cheap, deterministic analysis of the character's OWN recent model turns —
    fed to the **director** prompt only (never the final generation), so the
    director can deliberately break a rut. Pure (no LLM, string-only).

    - ``recent_openings`` — the first ~3 content words of each recent model turn's
      first dialogue line (trivial openers dropped), newest last.
    - ``recent_message_counts`` — visible item count per recent model turn.
    - ``last_model_ended_with_question`` — did the most recent model turn's last
      dialogue line end on a ``?``.
    - ``overused_phrases`` — 2-/3-grams recurring across recent model dialogue
      (count >= 2), capped.
    """
    turns = transcript.get("turns") or []
    model_turns = [t for t in turns if t.get("author") == Author.model.value][-lookback:]

    recent_openings: list[str] = []
    for t in model_turns:
        dlg = _model_dialogue_items(t)
        if not dlg:
            continue
        words = _WORD_RE.findall(dlg[0].lower())
        # Skip only *leading* trivial openers (they carry no structural signal),
        # then keep the next few words verbatim.
        i = 0
        while i < len(words) and words[i] in _PATTERN_STOP_OPENERS:
            i += 1
        kept = words[i:i + 3]
        if kept:
            recent_openings.append(" ".join(kept))

    recent_message_counts = [_visible_model_item_count(t) for t in model_turns]

    last_model_ended_with_question = False
    for t in reversed(model_turns):
        dlg = _model_dialogue_items(t)
        if dlg:
            last_model_ended_with_question = dlg[-1].rstrip().endswith("?")
            break

    # n-gram frequency across all recent model dialogue.
    counts: dict[str, int] = {}
    for t in model_turns:
        for line in _model_dialogue_items(t):
            words = _WORD_RE.findall(line.lower())
            for n in (2, 3):
                for i in range(len(words) - n + 1):
                    gram = " ".join(words[i:i + n])
                    counts[gram] = counts.get(gram, 0) + 1
    overused_phrases = [g for g, c in counts.items() if c >= 2]
    # Prefer longer (3-gram) repeats first, then alphabetical for determinism; cap.
    overused_phrases.sort(key=lambda g: (-len(g.split()), g))
    overused_phrases = overused_phrases[:5]

    return {
        "recent_openings": recent_openings,
        "recent_message_counts": recent_message_counts,
        "last_model_ended_with_question": last_model_ended_with_question,
        "overused_phrases": overused_phrases,
    }


def render_pattern_block(summary: dict) -> str:
    """Render the RECENT PATTERN block for the director prompt, or ``""`` when
    there is nothing notable yet (same vanish-when-empty convention as the feel
    blocks, so the ``{{var.pattern_block}}`` token simply disappears)."""
    openings = summary.get("recent_openings") or []
    counts = summary.get("recent_message_counts") or []
    overused = summary.get("overused_phrases") or []
    ended_q = summary.get("last_model_ended_with_question")
    lines: list[str] = []
    if openings:
        lines.append("Recent openings: " + "; ".join(openings))
    if counts:
        lines.append("Recent message counts: " + ", ".join(str(c) for c in counts))
    if overused:
        lines.append("Overused phrases: " + "; ".join(overused))
    if ended_q:
        lines.append("The last reply ended on a question.")
    if not lines:
        return ""
    body = "\n".join(f"- {ln}" for ln in lines)
    return (
        "RECENT PATTERN — what this character has been doing lately. Deliberately "
        "BREAK these patterns so the conversation does not get monotonous:\n"
        f"{body}"
    )


def renderable_vars(context_vars: dict) -> dict:
    """``context_vars`` minus the internal underscore-prefixed carriers
    (``_mem_query``, ``_pattern_block``, ``_transcript_messages`` — some are
    lists/dicts) that must never reach ``get_text``'s ``{{var.*}}`` substitution
    (compose treats a non-string variable value as a nested prompt node). Use this
    at every call site that feeds a context bundle to ``get_text``."""
    return {k: v for k, v in context_vars.items() if not k.startswith("_")}


def build_context(conversation: dict, character: dict, transcript: dict) -> dict[str, str]:
    """Build the prompt variable bundle from the conversation, counterpart sheet,
    and transcript. **Pure** (no LLM, no network) so the later token-budget change
    (window unit is currently *turns*) is isolated here.

    Also carries ``_mem_query`` — the memory-retrieval query for the turn step's
    ``{{memory}}`` config — kept here (not rendered into any prompt) so retrieval
    targets what the user just said, falling back to the whole window.
    """
    config = conversation.get("config") or {}
    window = config.get("context_window_turns", 12)
    turns = transcript.get("turns") or []
    recent = turns[-window:] if isinstance(window, int) and window > 0 else turns

    transcript_text = _flatten_transcript(recent, character)
    persona = ((conversation.get("device_user") or {}).get("persona") or "").strip()
    return {
        "character": render_character_context(character),
        "scenario": (conversation.get("scenario") or "").strip(),
        "role_instructions": (conversation.get("role_instructions") or "").strip(),
        "user_persona": persona or _EMPTY_PERSONA,
        "transcript": transcript_text,
        # Active Command-plugin orders, gathered from the WHOLE transcript (not the
        # window) so a standing order never scrolls out of scope. "" when none.
        "standing_orders": _render_standing_orders(_collect_standing_orders(turns)),
        # Dialogue Feel System: the stable profile + concrete examples. Each is a
        # self-contained block (or "") so the turn/variety prompts can drop them in
        # directly. The per-turn *roll* (RNG) is added later in build_turn_request.
        "voice_feel": render_voice_feel(character, conversation),
        "voice_examples": render_voice_examples(character, conversation),
        "_mem_query": _latest_user_text(recent) or transcript_text,
        # Recent-pattern block for the director prompt (over the WHOLE transcript's
        # recent model turns, its own lookback). Underscore-prefixed: never rendered
        # into the turn prompt. build_context returns only strings (the bundle is
        # passed as get_text `variables=` by several callers), so the raw summary
        # dict for the trace is recomputed in run_model_turn, not carried here.
        "_pattern_block": render_pattern_block(
            build_recent_pattern_summary(transcript, character)
        ),
        # The recent window as real role messages (the structured-history path).
        # Underscore-prefixed: a list, never rendered into a single-prompt template.
        "_transcript_messages": _transcript_to_messages(recent, character),
    }


# ---- structured chat messages ----------------------------------------------

# The final user turn: a short, strong instruction. Static (no tokens).
_STRUCTURED_FINAL_INSTRUCTION = (
    "Write your next text-message reply now. Reply to the latest message above, "
    "follow the plan for this reply, stay in character, and output only the tagged "
    "lines — nothing else."
)


def build_structured_messages(
    context_vars: dict,
    *,
    director_block: str,
    transcript_messages: list[dict],
) -> list[dict]:
    """Assemble the turn step's role array (structured-history mode). The context
    blocks are already resolved strings (from :func:`build_context`), so they go in
    as **literal** content; only the memory message carries the deferred
    ``{{memory}}`` token (filled by the executor at run time, after retrieval).

    Order — system framing first, the conversation as real turns, then the
    strongest-compliance blocks (standing orders, memory, plan) just before the
    final user instruction:

    1. system: identity + rules + output format (the ``turn_system`` prompt)
    2. system: character + scenario + role instructions + persona
    3. system: voice feel + examples (when any)
    4. (conversation: user/assistant/summary turns)
    5. system: STANDING ORDERS (when any)
    6. system: memory (the lone ``{{memory}}`` token)
    7. system: director plan / feel roll (when any)
    8. user: final instruction
    """
    msgs: list[dict] = [
        {"role": "system", "content": get_text("prattletale", "turn_system")},
        {"role": "system", "content": (
            "WHO YOU ARE:\n<character>\n" + context_vars.get("character", "") + "\n</character>\n\n"
            "THE SITUATION:\n<scenario>\n" + context_vars.get("scenario", "") + "\n</scenario>\n\n"
            "HOW TO PLAY THIS ROLE:\n<role_instructions>\n"
            + context_vars.get("role_instructions", "") + "\n</role_instructions>\n\n"
            "WHO YOU ARE TEXTING:\n<user_persona>\n"
            + context_vars.get("user_persona", "") + "\n</user_persona>"
        )},
    ]
    voice = "\n\n".join(
        b for b in (context_vars.get("voice_feel", ""), context_vars.get("voice_examples", "")) if b
    )
    if voice:
        msgs.append({"role": "system", "content": voice})

    msgs.extend(transcript_messages)

    if (context_vars.get("standing_orders") or "").strip():
        msgs.append({"role": "system", "content": context_vars["standing_orders"]})
    # Memory is the only message carrying a template token; the executor fills it.
    msgs.append({"role": "system", "content": (
        "THINGS YOU REMEMBER (background only; may be empty). Weave them in naturally "
        "only when they fit; never read them aloud, list them, or say you 'remember' "
        "them.\n<memory>\n{{memory}}\n</memory>"
    )})
    if (director_block or "").strip():
        msgs.append({"role": "system", "content": director_block})
    msgs.append({"role": "user", "content": _STRUCTURED_FINAL_INSTRUCTION})
    return msgs


# ---- request shape ---------------------------------------------------------

def build_turn_request(
    context_vars: dict[str, str],
    llm: ChainLLMConfig,
    *,
    variety: bool = True,
    dialogue_feel_roll_enabled: bool = True,
    plan: Optional[dict] = None,
    structured_chat_history: bool = True,
    counterpart_id: str = "",
    session_id: str = "",
) -> ChainJobRequest:
    """Build the ``turn`` -> (``variety``) -> ``guard`` chain. Each step's prompt
    comes from Prompt Pal with the context vars substituted; the variety and guard
    steps run over ``{{previous}}`` (the prior step's output), and the last step's
    output becomes ``final_output.txt``.

    The optional **variety** pass (anti-monotony) sits between the draft and the
    format guard so the guard still has the last word on format. It is skipped
    when ``variety`` is False or the ``(prattletale, variety)`` prompt is empty.

    The **turn** step carries a memory config: the executor searches the
    ``character:<counterpart>`` and ``session:<conversation>`` scopes for what the
    user just said and injects the result into the prompt's ``{{memory}}`` token
    (fail-soft — an empty/disabled subsystem yields an empty block). Only the turn
    step retrieves; the variety/guard passes run over ``{{previous}}``.

    The per-turn ``plan`` (the director's validated JSON) is rendered into the
    strong-compliance block and injected through the ``{{var.dialogue_feel_roll}}``
    slot — it subsumes the old shade/move/cadence roll. When ``plan`` is None
    (director off or failed) the block falls back to the weighted wildcard feel
    roll, so that slot is always populated the same self-contained way.
    """
    # The director plan is the per-turn behavior block; fall back to the weighted
    # wildcard feel roll when the director produced nothing. Either way it lands in
    # the {{var.dialogue_feel_roll}} slot (a self-contained block, or "").
    roll = render_director_plan(plan) if plan else ""
    if not roll:
        roll = resolve_dialogue_feel_roll(counterpart_id, enabled=dialogue_feel_roll_enabled)
    # Internal underscore-prefixed carriers never reach the turn prompt's {{var.*}}.
    rendered_vars = renderable_vars(context_vars)
    prompt_vars = {**rendered_vars, "dialogue_feel_roll": roll}
    memory = {
        "enabled": True,
        "query": "{{var.mem_query}}",
        "scopes": [
            {"scope_type": "character", "scope_id": "{{var.counterpart_id}}"},
            {"scope_type": "session", "scope_id": "{{var.session_id}}"},
            # Broader buckets so universal user facts (name, pronouns, preferences)
            # reach every character: app:prattletale is shared across all of this
            # app's chats; global is shared across the whole server.
            {"scope_type": "app", "scope_id": "prattletale"},
            {"scope_type": "global", "scope_id": "global"},
        ],
        "inject_as": "memory",
        "top_k": 6,
        "max_chars": 1200,
    }
    # The whole chat-turn pipeline runs no-thinking: reasoning degrades the
    # in-character reply, and on variety/guard a verbose think trace can exhaust
    # max_tokens and return empty content ("model output produced no items").
    #
    # The turn step is either a structured role array (default) or the legacy
    # single flattened prompt. Both carry the SAME memory config (the executor
    # fills {{memory}} in the structured memory message or the single prompt). In
    # structured mode the director plan/feel roll is the dedicated plan message; in
    # single-prompt mode it's spliced through the {{var.dialogue_feel_roll}} slot.
    if structured_chat_history:
        messages = build_structured_messages(
            context_vars,
            director_block=roll,
            transcript_messages=context_vars.get("_transcript_messages") or [],
        )
        steps = [_llm_step(1, "turn", "Turn", memory=memory, thinking=False, messages=messages)]
    else:
        # resolve_wildcards expands %%name%% tokens (e.g. the per-turn message-shape
        # pick) with a fresh weighted draw each turn — the server-side equivalent of
        # the frontend wildcard pass, which this prompt never goes through.
        turn_prompt = resolve_wildcards(get_text("prattletale", "turn", variables=prompt_vars))
        steps = [_llm_step(1, "turn", "Turn", turn_prompt, memory=memory, thinking=False)]
    number = 2
    if variety:
        variety_prompt = get_text("prattletale", "variety", variables=prompt_vars)
        if variety_prompt.strip():
            steps.append(_llm_step(number, "variety", "Variety",
                                   resolve_wildcards(variety_prompt), thinking=False))
            number += 1
    # Format hygiene is no longer an unconditional LLM guard step — it's a
    # deterministic post-execution pass in run_model_turn, with an LLM repair
    # fallback only when the parser still can't produce items.
    return ChainJobRequest(
        title="Prattletale turn",
        input=context_vars.get("transcript", ""),
        llm=llm,
        steps=steps,
        variables={
            "mem_query": context_vars.get("_mem_query", ""),
            "counterpart_id": counterpart_id,
            "session_id": session_id,
        },
    )


async def run_director(
    context_vars: dict[str, str],
    llm: ChainLLMConfig,
    *,
    counterpart_id: str = "",
    session_id: str = "",
) -> tuple[Optional[dict], str]:
    """Run the per-turn director: a one-step LLM pre-pass that *plans* the next
    reply (shape, move, stance, what to reference/avoid) as strict JSON. Returns
    ``(plan, raw)`` — the validated/normalized plan dict (or ``None`` when nothing
    usable parsed, so the caller falls back to the weighted wildcard feel roll) plus
    the director's raw output (for the trace).

    Runs as its own tiny on-disk job so it reuses the full LLM plumbing (endpoint
    resolution, model swap, on-disk trace) and is independently traceable; it never
    mutates the conversation. The director runs WITH thinking on (the rest of the
    chat pipeline is no-think) for sturdier JSON. The recent-pattern block reaches
    it as ``{{var.pattern_block}}``."""
    dvars = renderable_vars(context_vars)
    dvars["pattern_block"] = context_vars.get("_pattern_block", "")
    prompt = get_text("prattletale", "director", variables=dvars)
    request = ChainJobRequest(
        title="Prattletale director",
        input=context_vars.get("transcript", ""),
        llm=llm,
        steps=[_llm_step(1, "director", "Director", prompt, thinking=True)],
        variables={"counterpart_id": counterpart_id, "session_id": session_id},
    )
    status = create_job(JOB_TYPE_DIRECTOR, request.model_dump(), request.input)
    job_dir = find_job_dir(status["job_id"])
    if job_dir is None:  # pragma: no cover — create_job just made it
        return None, ""
    await execute_chain_job(status["job_id"], job_dir, request)
    raw = _read_final_output(job_dir)
    return parse_director_plan(raw), raw


async def run_repair(raw: str, llm: ChainLLMConfig) -> str:
    """Last-resort LLM reformat of a reply the deterministic pass + parser couldn't
    handle. Runs as its own tiny one-step job over the cleaned/raw text (``{{input}}``)
    and returns the reformatted text (``""`` if the job produced nothing). Caller
    re-runs the deterministic pass + parse on the result."""
    prompt = get_text("prattletale", "repair")
    request = ChainJobRequest(
        title="Prattletale repair",
        input=raw,
        llm=llm,
        steps=[_llm_step(1, "repair", "Repair", prompt, thinking=False)],
    )
    status = create_job(JOB_TYPE_REPAIR, request.model_dump(), request.input)
    job_dir = find_job_dir(status["job_id"])
    if job_dir is None:  # pragma: no cover — create_job just made it
        return ""
    await execute_chain_job(status["job_id"], job_dir, request)
    return _read_final_output(job_dir)


def _read_final_output(job_dir: Path) -> str:
    p = job_dir / "final_output.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _collect_steps(job_dir: Path, request: ChainJobRequest) -> list[dict]:
    """Pair the request's ordered steps with the outputs the executor wrote under
    ``steps/NNN_<id>/`` so the trace is self-describing (drives SP6's node-graph).

    Best-effort: a step whose ``prompt.txt``/``output.txt`` can't be read records
    that field as ``None`` rather than failing the turn. The turn pipeline never
    loops (no gotos), so each step ran exactly once (``NNN_<id>``, no ``_xII``).
    """
    steps_dir = job_dir / "steps"
    collected: list[dict] = []
    for step in request.steps:
        alt = step.alternatives[0] if step.alternatives else None
        rendered_prompt = alt.prompt if alt is not None else None
        output: Optional[str] = None
        # ``None`` = the step had no memory retrieval; ``""`` = it searched and
        # nothing matched; a block = the memories injected into context. Lets the
        # trace UI show exactly which memories a turn pulled in.
        memory: Optional[str] = None
        step_dir = steps_dir / f"{step.number:03d}_{step.id}"
        if step_dir.is_dir():
            prompt_file = step_dir / "prompt.txt"
            if prompt_file.exists():
                rendered_prompt = prompt_file.read_text(encoding="utf-8")
            output_file = step_dir / "output.txt"
            if output_file.exists():
                output = output_file.read_text(encoding="utf-8")
            memory_file = step_dir / "memory.txt"
            if memory_file.exists():
                memory = memory_file.read_text(encoding="utf-8")
        collected.append({
            "number": step.number,
            "id": step.id,
            "name": step.name,
            "prompt": rendered_prompt,
            "output": output,
            "memory": memory,
        })
    return collected


# ---- the pipeline ----------------------------------------------------------

async def run_model_turn(
    conversation_id: str,
    llm: Optional[ChainLLMConfig] = None,
    *,
    replace_turn_id: Optional[str] = None,
    add_version_turn_id: Optional[str] = None,
    synthesize: bool = True,
) -> tuple[dict, str]:
    """Run the full pipeline for ``conversation_id`` and persist a model turn.

    Returns ``(model_turn, job_id)``. On **any** failure (no counterpart, LLM
    error, empty parse) it appends a ``system_error`` turn via
    :func:`store.append_error_turn` and returns that turn instead of raising — so
    the router can return HTTP 200 with an inline error bubble, and a failed turn
    never poisons the next attempt (``system_error`` items are skipped by
    :func:`build_context`).

    When ``replace_turn_id`` is given (the **retry** path) the turn is excluded
    from the context window and, on success, overwritten **in place** via
    :func:`store.replace_turn` (same ``turn_id``/position, new committed items) so
    the chat layout stays stable. A retry that fails again appends a fresh
    ``system_error`` turn like any other failure.

    When ``add_version_turn_id`` is given (the **regenerate** path) the turn is
    likewise excluded from context, but on success the new draft is *appended* as
    a fresh version via :func:`store.add_turn_version` (keeping the prior
    version(s) so the user can flip between them). A regenerate that **fails**
    re-raises instead of appending a ``system_error`` turn — the existing turn and
    its versions must stay intact — so the caller (the router) surfaces the error.
    """
    from .prompts import parse_items  # lazy: avoids a prompts<->generator import cycle
    from .repair import repair_output_deterministic

    conversation = store.get_conversation(conversation_id)
    transcript = store.get_transcript(conversation_id)
    if conversation is None or transcript is None:
        raise GenerationError(f"conversation not found: {conversation_id}")

    exclude_turn_id = replace_turn_id or add_version_turn_id
    if exclude_turn_id is not None:
        # Re-run against the transcript with the turn being retried/regenerated excluded.
        transcript = {
            **transcript,
            "turns": [t for t in transcript.get("turns", []) if t.get("id") != exclude_turn_id],
        }

    job_id: Optional[str] = None
    context_vars: Optional[dict] = None
    raw = ""
    try:
        character = get_character(conversation["counterpart_character_id"])
        if character is None:
            raise GenerationError(
                f"counterpart character not found: {conversation['counterpart_character_id']}"
            )
        resolved = _resolve_llm(llm)
        context_vars = build_context(conversation, character, transcript)
        config = conversation.get("config") or {}
        variety = bool(config.get("variety_pass_enabled", False))
        roll_enabled = bool(config.get("dialogue_feel_roll_enabled", True))
        director_enabled = bool(config.get("director_enabled", True))
        structured = bool(config.get("structured_chat_history", True))
        # The per-turn director (default on): an LLM pre-pass that plans the reply.
        # A failed or empty director (-> None) falls back to the wildcard feel roll
        # inside build_turn_request. Never lets a director error sink the reply.
        plan: Optional[dict] = None
        plan_raw = ""
        if director_enabled:
            try:
                plan, plan_raw = await run_director(
                    context_vars, resolved,
                    counterpart_id=conversation["counterpart_character_id"],
                    session_id=conversation_id,
                )
            except Exception:  # noqa: BLE001 — director is best-effort; fall back to wildcards
                plan, plan_raw = None, ""
        request = build_turn_request(
            context_vars,
            resolved,
            variety=variety,
            dialogue_feel_roll_enabled=roll_enabled,
            plan=plan,
            structured_chat_history=structured,
            counterpart_id=conversation["counterpart_character_id"],
            session_id=conversation_id,
        )

        status = create_job(JOB_TYPE, request.model_dump(), request.input)
        job_id = status["job_id"]
        job_dir = find_job_dir(job_id)
        if job_dir is None:  # pragma: no cover — create_job just made it
            raise GenerationError("job directory disappeared after creation")

        await execute_chain_job(job_id, job_dir, request)
        raw = _read_final_output(job_dir)
        # Deterministic-first repair: a cheap Python cleanup before the parser. Only
        # when that still won't parse do we spend an LLM repair call (config-gated).
        cleaned = repair_output_deterministic(raw)
        try:
            items = parse_items(cleaned)
            repair_info: dict = {"mode": "deterministic", "llm_used": False}
        except GenerationError:
            if not bool(config.get("repair_enabled", True)):
                raise
            repaired = await run_repair(cleaned or raw, resolved)
            items = parse_items(repair_output_deterministic(repaired))
            repair_info = {"mode": "llm", "llm_used": True, "repaired_raw": repaired}

        if add_version_turn_id is not None:
            turn = store.add_turn_version(conversation_id, add_version_turn_id, items, job_id=job_id)
        elif replace_turn_id is not None:
            turn = store.replace_turn(conversation_id, replace_turn_id, items, job_id=job_id)
        else:
            turn = store.append_model_turn(conversation_id, items, job_id=job_id)
        if turn is None:  # pragma: no cover — transcript/turn checked above
            raise GenerationError("transcript disappeared while persisting model turn")

        # Voice is additive and best-effort: the text turn is already committed,
        # so a synth failure degrades to text instead of failing the reply.
        # The live chat path passes synthesize=False and instead synthesizes each
        # message lazily (per the per-item audio endpoint) so the reply isn't
        # blocked on every clip; eager synth stays available for other callers.
        voice_error: Optional[str] = None
        if synthesize:
            try:
                audio_map = await synthesize_turn(conversation, character, turn)
                if audio_map:
                    updated = store.apply_audio(conversation_id, turn["id"], audio_map)
                    if updated is not None:
                        turn = updated
            except Exception as exc:  # noqa: BLE001 — never let voice sink the reply
                voice_error = str(exc)

        turn_alt = request.steps[0].alternatives[0]
        store.write_trace(conversation_id, turn["id"], {
            "job_id": job_id,
            "prompt_version": PRATTLETALE_PROMPT_VERSION,
            "context_input": context_vars,
            "pattern_summary": build_recent_pattern_summary(transcript, character),
            "director_plan": plan,
            "director_plan_raw": plan_raw,
            "structured_messages": turn_alt.messages if structured else None,
            "raw_final_output": raw,
            "repair": repair_info,
            "parsed_items": items,
            "steps": _collect_steps(job_dir, request),
            "reveal_schedule": reveal_schedule(turn),
            "voice_error": voice_error,
            "error": None,
        })
        return turn, job_id
    except Exception as exc:  # noqa: BLE001 — any failure becomes an inline error turn
        # Regenerate must not destroy the existing turn / its versions on failure:
        # re-raise so the router can surface the error and the turn stays intact.
        if add_version_turn_id is not None:
            raise
        error_turn = store.append_error_turn(conversation_id, str(exc), job_id=job_id)
        if error_turn is not None:
            store.write_trace(conversation_id, error_turn["id"], {
                "job_id": job_id,
                "context_input": context_vars,
                "raw_final_output": raw,
                "parsed_items": [],
                "error": str(exc),
            })
        return error_turn or {}, job_id or ""
