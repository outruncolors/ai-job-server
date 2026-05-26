"""Tick driver: per-tick LLM free-choice over actions for every occupant.

On each tick, every occupied room's resident takes exactly one action. The
choice is made by the LLM (Continue is one option for an ongoing multi-tick
activity); the chosen action runs and its result is written to memory via the
context pipeline. One LOW-lane job runs a whole tick (see ``sim_clock``); each
*decision* is its own short chain job (``execute_chain_job`` directly, like the
generator), so it's visible and debuggable in the Jobs page.

``run_tick`` is resilient: a per-resident failure is logged and skipped, never
aborting the whole tick.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Optional

from ...chain.executor import execute_chain_job
from ...chain.models import Alternative, ChainJobRequest, ChainLLMConfig, ChainStep
from ...jobs import create_job, find_job_dir
from ...llm_config import get_default_as_chain_llm_config
from . import (
    activity_store,
    context_pipeline,
    event_store,
    memory_index,
    residents_store,
    rooms,
)
from .actions import breakpoint_clause, get_action, list_actions
from .generator import _strip_fences

log = logging.getLogger(__name__)

DECISION_JOB_TYPE = "blaboratory_action"


def next_tick() -> int:
    """The next tick number to run (one past the highest logged tick)."""
    return event_store.max_tick() + 1


def _disable_thinking(llm: ChainLLMConfig) -> ChainLLMConfig:
    if llm.chat_template_kwargs is None:
        return llm.model_copy(update={"chat_template_kwargs": {"enable_thinking": False}})
    return llm


def decision_node(activity: Optional[dict]) -> str:
    """The ``[Your Action]`` block: the menu of actions + Continue + breakpoint."""
    lines = ["It is your turn to act. Choose ONE thing to do this tick. Options:"]
    for a in list_actions():
        lines.append(f'- "{a.name}": {a.description}')
    if activity:
        ongoing = activity.get("action")
        count = activity.get("count", 1)
        lines.append(
            f'- "continue": keep doing your current activity ("{ongoing}"), '
            f"ongoing for {count} tick(s)."
        )
        act = get_action(ongoing) if ongoing else None
        if act:
            clause = breakpoint_clause(act, count)
            if clause:
                lines.append(clause)
    lines.append(
        'Respond with ONLY a JSON object like {"action": "<name>", "args": {}} — '
        "no commentary, no code fences."
    )
    return "\n".join(lines)


def _parse_choice(text: str) -> tuple[str, dict]:
    """Parse the LLM's JSON action choice; fall back to idle on any trouble."""
    try:
        data = json.loads(_strip_fences(text))
        action = data.get("action")
        args = data.get("args")
        if isinstance(action, str) and (action == "continue" or get_action(action)):
            return action, args if isinstance(args, dict) else {}
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return "idle", {}


async def _choose(context: str, llm: ChainLLMConfig, *, label: str) -> tuple[str, dict]:
    """Run a one-step decision chain over the assembled context; return (action, args)."""
    req = ChainJobRequest(
        title=f"[blab] {label}",
        input=context,
        llm=llm,
        steps=[
            ChainStep(
                number=1,
                id="decide",
                name="Decide",
                type="llm",
                alternatives=[Alternative(prompt="{{input}}")],
            )
        ],
    )
    status = create_job(DECISION_JOB_TYPE, req.model_dump(), req.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        return "idle", {}
    await execute_chain_job(job_id, job_dir, req)
    out = job_dir / "final_output.txt"
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    return _parse_choice(text)


async def _act_one(resident: dict, tick: int, llm: ChainLLMConfig, deps) -> str:
    """Decide + execute + persist one resident's action; return the action name."""
    rid = resident["id"]
    activity = activity_store.get_activity(rid)
    node = decision_node(activity)
    context = await context_pipeline.build_context(resident, action_node=node, tick=tick)
    choice, args = await _choose(context, llm, label=f"{resident.get('name', rid)} @ tick {tick}")

    if choice == "continue" and activity:
        action = get_action(activity["action"]) or get_action("idle")
        count = activity["count"] + 1
    else:
        action = get_action(choice) or get_action("idle")
        count = 1

    result = await action.run(resident, tick, context, args, deps=deps)
    context_pipeline.write_phase(resident, tick, result)

    if action.multi_tick:
        activity_store.set_activity(rid, action.name, count)
    else:
        activity_store.clear_activity(rid)
    return action.name


async def run_tick(tick_number: Optional[int] = None, *, llm: Optional[ChainLLMConfig] = None) -> dict:
    """Run one tick: every occupant takes one action.

    Returns a summary dict ``{"tick", "acted": [...], "skipped": <reason?>}``.
    If no default LLM is configured the tick is skipped cleanly.
    """
    if tick_number is None:
        tick_number = next_tick()

    if llm is None:
        try:
            llm = get_default_as_chain_llm_config()
        except RuntimeError as exc:
            log.warning("Blaboratory tick %s skipped: %s", tick_number, exc)
            return {"tick": tick_number, "acted": [], "skipped": "no_default_llm"}
    llm = _disable_thinking(llm)

    # Backfill the vector index before any gather so retrieval sees this tick's
    # and prior un-indexed rows. No-op (logged once) without the embed server.
    try:
        await memory_index.index_pending()
    except Exception:  # noqa: BLE001 — indexing must never abort the tick
        log.exception("Blaboratory tick %s: index_pending failed", tick_number)

    deps = SimpleNamespace(busy=set(), llm=llm)
    acted: list[dict] = []
    for room_id, rid in rooms.occupied_rooms():
        if rid in deps.busy:  # forfeited their action (e.g. a phone-call callee)
            continue
        resident = residents_store.get_resident(rid)
        if resident is None:  # dangling occupancy pointer
            continue
        try:
            name = await _act_one(resident, tick_number, llm, deps)
            acted.append({"room_id": room_id, "resident_id": rid, "action": name})
        except Exception:  # noqa: BLE001 - one resident's failure must not abort the tick
            log.exception("Blaboratory tick %s: resident %s failed", tick_number, rid)
    return {"tick": tick_number, "acted": acted}
