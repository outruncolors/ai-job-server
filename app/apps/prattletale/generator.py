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
from ...prompt_pal.service import get_guard, get_text
from ...wildcards import resolve_wildcards
from ..hoodat.characters_store import get_character
from ..hoodat.prompts import render_character_context
from . import store
from .feel import (
    parse_director_roll,
    render_voice_examples,
    render_voice_feel,
    resolve_dialogue_feel_roll,
)
from .models import Author, ItemType
from .voice import reveal_schedule, synthesize_turn

JOB_TYPE = "prattletale_turn"
# The optional feel-director pre-pass runs as its own tiny one-step job (reuses
# the full LLM plumbing: endpoint resolution, model swap, on-disk trace).
JOB_TYPE_DIRECTOR = "prattletale_feel_director"

# Rendered when the device user has no persona, so the prompt's <user_persona>
# section never collapses to a dangling label with empty contents.
_EMPTY_PERSONA = "(No specific persona — an ordinary conversational partner.)"


class GenerationError(Exception):
    """Raised when a turn cannot produce a usable reply. The canonical home for
    this exception (SP2's parser re-imports it from here)."""


# ---- LLM resolution --------------------------------------------------------

def _resolve_llm(llm: Optional[ChainLLMConfig]) -> ChainLLMConfig:
    if llm is None:
        try:
            llm = get_default_as_chain_llm_config()
        except RuntimeError as exc:
            raise GenerationError(str(exc)) from exc
    # Reasoning is controlled per chain step now (see _llm_step's `thinking`):
    # the in-character `turn` runs without it, utility steps keep the default.
    return llm


def _llm_step(
    number: int, step_id: str, name: str, prompt: str, *,
    memory: Optional[dict] = None, thinking: Optional[bool] = None,
) -> ChainStep:
    """Build a single-alternative ``llm`` step. When ``memory`` is given, the
    alternative carries a :class:`MemoryStepConfig` so the executor retrieves a
    memory block and exposes it to the prompt via the ``{{memory}}`` token (and
    writes ``steps/NNN_<id>/memory.txt`` for the trace). ``thinking`` overrides
    the project reasoning default (None = default-on; False for the in-character
    reply, which roleplay best practice runs without a reasoning trace)."""
    alt = Alternative(
        prompt=prompt,
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
        ]
        text = " ".join(r for r in (_render_item(it) for it in visible) if r).strip()
        if text:
            return text
    return ""


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
    }


# ---- request shape ---------------------------------------------------------

def build_turn_request(
    context_vars: dict[str, str],
    llm: ChainLLMConfig,
    *,
    variety: bool = True,
    dialogue_feel_roll_enabled: bool = True,
    dialogue_feel_roll: Optional[str] = None,
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
    """
    # The per-turn Dialogue Feel roll — added to the prompt vars so both the turn
    # and the variety step see the same roll. ``dialogue_feel_roll`` (the
    # context-aware director's output) overrides when provided; otherwise it's a
    # fresh weighted draw of the Move / Shade / Cadence wildcards (character-override
    # aware). Empty when disabled, the director yielded nothing, or wildcards absent.
    roll = (dialogue_feel_roll if dialogue_feel_roll is not None
            else resolve_dialogue_feel_roll(counterpart_id, enabled=dialogue_feel_roll_enabled))
    prompt_vars = {**context_vars, "dialogue_feel_roll": roll}
    # resolve_wildcards expands %%name%% tokens (e.g. the per-turn message-shape
    # pick) with a fresh weighted draw each turn — the server-side equivalent of
    # the frontend wildcard pass, which this prompt never goes through.
    turn_prompt = resolve_wildcards(get_text("prattletale", "turn", variables=prompt_vars))
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
    # The in-character reply runs without reasoning (it degrades roleplay); the
    # downstream variety/guard utility passes keep the default (thinking on).
    steps = [_llm_step(1, "turn", "Turn", turn_prompt, memory=memory, thinking=False)]
    number = 2
    if variety:
        variety_prompt = get_text("prattletale", "variety", variables=prompt_vars)
        if variety_prompt.strip():
            steps.append(_llm_step(number, "variety", "Variety", resolve_wildcards(variety_prompt)))
            number += 1
    guard_prompt = get_guard("prattletale", "turn")
    if guard_prompt:
        steps.append(_llm_step(number, "guard", "Guard", guard_prompt))
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


async def direct_feel_roll(
    context_vars: dict[str, str],
    llm: ChainLLMConfig,
    *,
    counterpart_id: str = "",
    session_id: str = "",
) -> str:
    """Run the feel director: a one-step LLM pre-pass that *chooses* this turn's
    dialogue feel from the conversation (vs the blind wildcard draw). Returns the
    parsed ``<dialogue_feel_roll>`` block, or ``""`` if it produced nothing usable
    (the caller then falls back to the wildcard draw).

    Runs as its own tiny on-disk job so it reuses the full LLM plumbing and is
    independently traceable; it never mutates the conversation."""
    prompt = get_text("prattletale", "feel_director", variables=context_vars)
    request = ChainJobRequest(
        title="Prattletale feel director",
        input=context_vars.get("transcript", ""),
        llm=llm,
        steps=[_llm_step(1, "feel_director", "Feel Director", prompt)],
        variables={"counterpart_id": counterpart_id, "session_id": session_id},
    )
    status = create_job(JOB_TYPE_DIRECTOR, request.model_dump(), request.input)
    job_dir = find_job_dir(status["job_id"])
    if job_dir is None:  # pragma: no cover — create_job just made it
        return ""
    await execute_chain_job(status["job_id"], job_dir, request)
    return parse_director_roll(_read_final_output(job_dir))


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
    """
    from .prompts import parse_items  # lazy: avoids a prompts<->generator import cycle

    conversation = store.get_conversation(conversation_id)
    transcript = store.get_transcript(conversation_id)
    if conversation is None or transcript is None:
        raise GenerationError(f"conversation not found: {conversation_id}")

    if replace_turn_id is not None:
        # Re-run against the transcript with the turn being retried excluded.
        transcript = {
            **transcript,
            "turns": [t for t in transcript.get("turns", []) if t.get("id") != replace_turn_id],
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
        variety = bool(config.get("variety_pass_enabled", True))
        roll_enabled = bool(config.get("dialogue_feel_roll_enabled", True))
        director_enabled = bool(config.get("dialogue_feel_director_enabled", False))
        # Context-aware roll (opt-in): let a director LLM choose the feel; a failed
        # or empty director (-> None) falls back to the wildcard draw inside
        # build_turn_request. Never lets a director error sink the reply.
        roll_override: Optional[str] = None
        if roll_enabled and director_enabled:
            try:
                roll_override = await direct_feel_roll(
                    context_vars, resolved,
                    counterpart_id=conversation["counterpart_character_id"],
                    session_id=conversation_id,
                ) or None
            except Exception:  # noqa: BLE001 — director is best-effort; fall back to wildcards
                roll_override = None
        request = build_turn_request(
            context_vars,
            resolved,
            variety=variety,
            dialogue_feel_roll_enabled=roll_enabled,
            dialogue_feel_roll=roll_override,
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
        items = parse_items(raw)

        if replace_turn_id is not None:
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

        store.write_trace(conversation_id, turn["id"], {
            "job_id": job_id,
            "context_input": context_vars,
            "raw_final_output": raw,
            "parsed_items": items,
            "steps": _collect_steps(job_dir, request),
            "reveal_schedule": reveal_schedule(turn),
            "voice_error": voice_error,
            "error": None,
        })
        return turn, job_id
    except Exception as exc:  # noqa: BLE001 — any failure becomes an inline error turn
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
