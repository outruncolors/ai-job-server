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
from ...chain.models import Alternative, ChainJobRequest, ChainLLMConfig, ChainStep
from ...jobs import create_job, find_job_dir
from ...llm_config import get_default_as_chain_llm_config
from ...prompt_pal.service import get_guard, get_text
from ...wildcards import resolve_wildcards
from ..hoodat.characters_store import get_character
from ..hoodat.prompts import render_character_context
from . import store
from .models import Author, ItemType
from .voice import reveal_schedule, synthesize_turn

JOB_TYPE = "prattletale_turn"

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
    # Want an in-character reply, not a reasoning trace (same rationale as Hoodat).
    if llm.chat_template_kwargs is None:
        llm = llm.model_copy(update={"chat_template_kwargs": {"enable_thinking": False}})
    return llm


def _llm_step(number: int, step_id: str, name: str, prompt: str) -> ChainStep:
    return ChainStep(
        number=number, id=step_id, name=name, type="llm",
        alternatives=[Alternative(prompt=prompt)],
    )


# ---- context assembly (pure) -----------------------------------------------

def _render_item(item: dict) -> str:
    """Render one item for the transcript script: dialogue (and a ``summary``
    recap) as plain text, every other (visible) type as a parenthesized stage
    direction."""
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
    """Flatten turns to a ``[Speaker] …`` script, skipping ``hidden_from_context``
    and ``system_error`` items. A turn with no visible items is dropped entirely
    (no dangling speaker label)."""
    lines: list[str] = []
    for turn in turns:
        visible = [
            it for it in (turn.get("items") or [])
            if not it.get("hidden_from_context")
            and it.get("type") != ItemType.system_error.value
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


def build_context(conversation: dict, character: dict, transcript: dict) -> dict[str, str]:
    """Build the prompt variable bundle from the conversation, counterpart sheet,
    and transcript. **Pure** (no LLM, no network) so the later token-budget change
    (window unit is currently *turns*) is isolated here.
    """
    config = conversation.get("config") or {}
    window = config.get("context_window_turns", 12)
    turns = transcript.get("turns") or []
    recent = turns[-window:] if isinstance(window, int) and window > 0 else turns

    persona = ((conversation.get("device_user") or {}).get("persona") or "").strip()
    return {
        "character": render_character_context(character),
        "scenario": (conversation.get("scenario") or "").strip(),
        "role_instructions": (conversation.get("role_instructions") or "").strip(),
        "user_persona": persona or _EMPTY_PERSONA,
        "transcript": _flatten_transcript(recent, character),
    }


# ---- request shape ---------------------------------------------------------

def build_turn_request(
    context_vars: dict[str, str], llm: ChainLLMConfig, *, variety: bool = True
) -> ChainJobRequest:
    """Build the ``turn`` -> (``variety``) -> ``guard`` chain. Each step's prompt
    comes from Prompt Pal with the context vars substituted; the variety and guard
    steps run over ``{{previous}}`` (the prior step's output), and the last step's
    output becomes ``final_output.txt``.

    The optional **variety** pass (anti-monotony) sits between the draft and the
    format guard so the guard still has the last word on format. It is skipped
    when ``variety`` is False or the ``(prattletale, variety)`` prompt is empty.
    """
    # resolve_wildcards expands %%name%% tokens (e.g. the per-turn message-shape
    # pick) with a fresh weighted draw each turn — the server-side equivalent of
    # the frontend wildcard pass, which this prompt never goes through.
    turn_prompt = resolve_wildcards(get_text("prattletale", "turn", variables=context_vars))
    steps = [_llm_step(1, "turn", "Turn", turn_prompt)]
    number = 2
    if variety:
        variety_prompt = get_text("prattletale", "variety", variables=context_vars)
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
    )


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
        step_dir = steps_dir / f"{step.number:03d}_{step.id}"
        if step_dir.is_dir():
            prompt_file = step_dir / "prompt.txt"
            if prompt_file.exists():
                rendered_prompt = prompt_file.read_text(encoding="utf-8")
            output_file = step_dir / "output.txt"
            if output_file.exists():
                output = output_file.read_text(encoding="utf-8")
        collected.append({
            "number": step.number,
            "id": step.id,
            "name": step.name,
            "prompt": rendered_prompt,
            "output": output,
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
        variety = bool((conversation.get("config") or {}).get("variety_pass_enabled", True))
        request = build_turn_request(context_vars, resolved, variety=variety)

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
