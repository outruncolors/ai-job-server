"""Phone call — an atomic, internally-structured conversation.

A caller reaches a callee on the speakerphone; the **callee's own LLM** accepts
or declines from its context. On accept, a conversation runs: pick an opening
topic → trade lines → after each exchange the speaker signals **continue**,
**segue** (drop back to topic-select with a "previous conversation" bridge), or
**end**. The whole call generates within the caller's tick; the callee forfeits
its own action that tick (marked busy on ``deps``). Each spoken line is written
to *both* participants' rooms so the conversation surfaces in each.

Design note / deviation: the design frames this as a single chain *sequence*
with weighted ``goto`` for terminate/segue. Here the turn loop is orchestrated in
Python, reusing ``execute_chain_job`` for each individual LLM turn (the same
direct-execution pattern as the resident generator and tick runner). That keeps
the accept→topic→exchange→terminate/segue shape while staying deterministic and
testable; re-encoding it as literal goto steps is a clean later refactor.
"""

from __future__ import annotations

import logging
import random
from typing import Optional

from ...chain.executor import execute_chain_job
from ...chain.models import Alternative, ChainJobRequest, ChainLLMConfig, ChainStep
from ...jobs import create_job, find_job_dir
from . import context_pipeline, residents_store, rooms, utterance_store

log = logging.getLogger(__name__)

CALL_JOB_TYPE = "blaboratory_call"
CALL_MAX_LINES = 8  # hard cap so a call always terminates


async def _run_llm(input_text: str, llm: ChainLLMConfig, *, label: str) -> str:
    """One LLM turn via the chain executor; returns the trimmed text output."""
    req = ChainJobRequest(
        title=f"[blab call] {label}",
        input=input_text,
        llm=llm,
        steps=[
            ChainStep(
                number=1,
                id="turn",
                name="Turn",
                type="llm",
                alternatives=[Alternative(prompt="{{input}}")],
            )
        ],
    )
    status = create_job(CALL_JOB_TYPE, req.model_dump(), req.input)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        return ""
    await execute_chain_job(job_id, job_dir, req)
    out = job_dir / "final_output.txt"
    return out.read_text(encoding="utf-8").strip() if out.exists() else ""


# ---- prompt fragments -----------------------------------------------------


def _accept_node(caller: dict) -> str:
    return (
        f"Your speakerphone is ringing — {caller.get('name', 'someone')} "
        f"({caller.get('occupation', 'a resident')}) is calling you. Decide whether to "
        "answer. Reply with exactly one word: ACCEPT or DECLINE."
    )


def _topic_node(caller: dict, callee: dict, prior: Optional[str]) -> str:
    base = (
        f"You ({caller.get('name')}) are on a call with {callee.get('name')}. "
        "Choose what to talk about and say your opening line on that topic. "
        "Reply with a single short spoken line (no narration)."
    )
    if prior:
        base += f"\nThe previous thread of the conversation was:\n{prior}\nNow steer to a fresh topic."
    return base


def _line_node(speaker: dict, other: dict, topic: str, history: list[tuple[str, str]]) -> str:
    convo = "\n".join(f"{who}: {line}" for who, line in history[-6:]) or "(the call just connected)"
    return (
        f"You are {speaker.get('name')} on a speakerphone call with {other.get('name')}. "
        f"Topic: {topic}\nConversation so far:\n{convo}\n"
        "Say your next spoken line. Reply with the line only (no narration)."
    )


def _continue_node(speaker: dict) -> str:
    return (
        "Decide how the call should proceed. Reply with exactly one word: "
        "CONTINUE (keep talking on this topic), SEGUE (change the subject), or END "
        "(wrap up and hang up)."
    )


def _parse_accept(text: str) -> bool:
    return "DECLINE" not in text.upper()


def _parse_continuation(text: str) -> str:
    up = text.upper()
    if "END" in up or "TERMINATE" in up or "GOODBYE" in up:
        return "end"
    if "SEGUE" in up:
        return "segue"
    return "continue"


def _emit_line(call_id: int, tick: int, speaker: dict, rooms_ids: list[int], body: str, seq: int) -> None:
    """Write one spoken line into every participant room (so it renders in both)."""
    for room_id in rooms_ids:
        if room_id is not None:
            utterance_store.append_utterance(
                call_id=call_id,
                tick=tick,
                speaker_resident_id=speaker["id"],
                room_id=room_id,
                body=body,
                seq=seq,
            )


async def run_call(
    caller: dict,
    callee: dict,
    tick: int,
    llm: ChainLLMConfig,
    *,
    deps=None,
) -> dict:
    """Place a call from ``caller`` to ``callee`` within the caller's tick.

    Returns a summary ``{call_id, accepted, lines, topics}``. On accept the
    callee is marked busy on ``deps`` so the tick runner skips its own action.
    """
    caller_room = rooms.room_of(caller["id"])
    callee_room = rooms.room_of(callee["id"])
    both_rooms = [caller_room, callee_room]

    # 1. callee accepts/declines from its own context.
    accept_ctx = await context_pipeline.build_context(callee, action_node=_accept_node(caller), tick=tick)
    accepted = _parse_accept(await _run_llm(accept_ctx, llm, label="accept?"))
    call_id = utterance_store.create_call(
        tick=tick,
        caller_resident_id=caller["id"],
        callee_resident_id=callee["id"],
        accepted=accepted,
    )

    if not accepted:
        utterance_store.end_call(call_id, "declined")
        return {"call_id": call_id, "accepted": False, "lines": 0, "topics": []}

    # Accepted: the callee forfeits its own action this tick.
    if deps is not None and hasattr(deps, "busy"):
        deps.busy.add(callee["id"])

    # 2. opening topic + line (caller).
    topics: list[str] = []
    history: list[tuple[str, str]] = []
    seq = 0

    opening = await _run_llm(
        await context_pipeline.build_context(caller, action_node=_topic_node(caller, callee, None), tick=tick),
        llm,
        label="topic",
    )
    topics.append(opening)
    seq += 1
    _emit_line(call_id, tick, caller, both_rooms, opening, seq)
    history.append((caller["name"], opening))

    # 3. exchange loop, alternating speakers, until END / segue-exhausted / cap.
    participants = [(callee, callee_room), (caller, caller_room)]
    turn = 0
    reason = "completed"
    while seq < CALL_MAX_LINES:
        decision = _parse_continuation(await _run_llm(_continue_node(caller), llm, label="continue?"))
        if decision == "end":
            reason = "completed"
            break
        if decision == "segue":
            topic = await _run_llm(
                await context_pipeline.build_context(
                    caller,
                    action_node=_topic_node(caller, callee, "\n".join(f"{w}: {l}" for w, l in history[-4:])),
                    tick=tick,
                ),
                llm,
                label="topic",
            )
            topics.append(topic)
        else:
            topic = topics[-1]

        speaker, _room = participants[turn % len(participants)]
        other = caller if speaker["id"] == callee["id"] else callee
        line = await _run_llm(
            await context_pipeline.build_context(speaker, action_node=_line_node(speaker, other, topic, history), tick=tick),
            llm,
            label="line",
        )
        seq += 1
        _emit_line(call_id, tick, speaker, both_rooms, line, seq)
        history.append((speaker["name"], line))
        turn += 1
    else:
        reason = "max_lines"

    utterance_store.end_call(call_id, reason)
    return {"call_id": call_id, "accepted": True, "lines": seq, "topics": topics}


def pick_callee(caller_id: str, *, busy: Optional[set] = None) -> Optional[dict]:
    """Pick a random other occupant to call (excluding busy residents)."""
    busy = busy or set()
    candidates = [
        rid for _room, rid in rooms.occupied_rooms() if rid != caller_id and rid not in busy
    ]
    if not candidates:
        return None
    return residents_store.get_resident(random.choice(candidates))
