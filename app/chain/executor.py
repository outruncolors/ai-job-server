from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .events import EventBus
from .llm_client import OpenAICompatibleLLMClient
from .models import DEFAULT_THINKING, Alternative, ChainJobRequest, ChainStep


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_id(raw: str, fallback: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)[:64]
    return sanitized if sanitized else fallback


def _write_chain_status(job_dir: Path, status: str, **extra: Any) -> None:
    status_file = job_dir / "status.json"
    data = json.loads(status_file.read_text(encoding="utf-8"))
    data["status"] = status
    data["updated_at"] = _now_iso()
    data.update(extra)
    status_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_step_status(
    step_dir: Path,
    *,
    id: str,
    name: str,
    type: str = "llm",
    status: str,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    error: Optional[str] = None,
    output_file: Optional[str] = None,
    tools: Optional[list] = None,
    step_number: Optional[int] = None,
    invocation: Optional[int] = None,
) -> None:
    data: dict = {
        "id": id,
        "name": name,
        "type": type,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "error": error,
        "output_file": output_file,
    }
    if tools is not None:
        data["tools"] = tools
    if step_number is not None:
        data["step_number"] = step_number
    if invocation is not None:
        data["invocation"] = invocation
    (step_dir / "status.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _append_log(job_dir: Path, text: str) -> None:
    with (job_dir / "logs.txt").open("a", encoding="utf-8") as f:
        f.write(text)


def patch_initial_chain_status(job_dir: Path, step_count: int) -> None:
    status_file = job_dir / "status.json"
    data = json.loads(status_file.read_text(encoding="utf-8"))
    data.update({
        "step_count": step_count,
        "progress": 0.0,
        "current_step_index": None,
        "current_step_id": None,
        "current_step_name": None,
        "outputs": None,
    })
    status_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_chain_steps(job_dir: Path) -> list[dict[str, Any]]:
    steps_dir = job_dir / "steps"
    if not steps_dir.exists():
        return []
    steps = []
    for step_dir in sorted(steps_dir.iterdir()):
        if not step_dir.is_dir():
            continue
        status_file = step_dir / "status.json"
        if status_file.exists():
            steps.append(json.loads(status_file.read_text(encoding="utf-8")))
    return steps


def _expand_steps(
    steps: list[ChainStep],
    seq_map: dict[str, dict],
    *,
    number_offset: int = 0,
    prefix: str = "",
    depth: int = 0,
) -> list[ChainStep]:
    """Flatten `type=sequence` references inline.

    Inner steps are renumbered as `outer_number * 1000 + inner_number` so they
    fit ahead of any later top-level numbers in `order`. Inner gotos that reference
    inner numbers are rewritten in the same scheme. Caller must pre-renumber the
    top-level steps; this function only rewrites inner numbers.
    """
    if depth > 20:
        raise RuntimeError("Sequence expansion depth exceeded 20 — possible cycle not caught at save time")
    import copy
    result: list[ChainStep] = []
    for step in steps:
        if step.type != "sequence":
            new_step = copy.deepcopy(step)
            if prefix:
                new_step.name = f"{prefix} > {new_step.name}"
            if number_offset:
                new_step.number = number_offset + new_step.number
                # Rewrite goto targets so they stay within this inner scope.
                if new_step.type == "goto":
                    for alt in new_step.alternatives:
                        if alt.target_step is not None:
                            alt.target_step = number_offset + alt.target_step
            result.append(new_step)
            continue
        # type == "sequence" — resolve and inline
        sequence_id = step.primary.sequence_id
        if not sequence_id:
            raise RuntimeError(f"Sequence step '{step.name}' has no sequence_id")
        seq = seq_map.get(sequence_id)
        if seq is None:
            raise RuntimeError(
                f"Sequence step '{step.name}' references unknown sequence id '{sequence_id}'"
            )
        new_prefix = f"{prefix} > {step.name}" if prefix else step.name
        # Renumber inner steps so they sort after this outer step but before the next one.
        outer_number = step.number if step.number > 0 else (len(result) + 1)
        inner_offset = outer_number * 1000
        from .sequences import steps_of
        sub_steps = [ChainStep(**s) for s in steps_of(seq)]
        result.extend(
            _expand_steps(
                sub_steps,
                seq_map,
                number_offset=inner_offset,
                prefix=new_prefix,
                depth=depth + 1,
            )
        )
    return result


def _renumber_top_level(steps: list[ChainStep]) -> None:
    """Ensure every top-level step has a positive, unique `number`. Assigns 1..N by
    position when missing, preserving existing user-assigned numbers when valid."""
    seen: set[int] = set()
    # First pass: collect already-assigned numbers
    for step in steps:
        if step.number > 0:
            if step.number in seen:
                raise ValueError(f"Duplicate step number {step.number} in request")
            seen.add(step.number)
    # Second pass: fill in zeros
    nxt = 1
    for step in steps:
        if step.number <= 0:
            while nxt in seen:
                nxt += 1
            step.number = nxt
            seen.add(nxt)
            nxt += 1


def _pick_alternative(step: ChainStep) -> Alternative:
    """Weighted random pick over a step's alternatives."""
    alts = step.alternatives
    if len(alts) == 1:
        return alts[0]
    weights = [max(1, a.weight) for a in alts]
    return random.choices(alts, weights=weights, k=1)[0]


def _resolve_variables(request: ChainJobRequest) -> dict[str, str]:
    """Merge caller-provided variable overrides on top of declared defaults."""
    result: dict[str, str] = {}
    for var in request.sequence_variables:
        result[var.name] = var.default
    for k, v in (request.variables or {}).items():
        result[k] = "" if v is None else str(v)
    return result


def _render(
    template: str,
    *,
    request: ChainJobRequest,
    text_output: str,
    context: str,
    step: ChainStep,
    step_inputs: dict[int, list[str]],
    step_outputs: dict[int, list[str]],
    variables: dict[str, str],
) -> str:
    from .template import render_template

    return render_template(
        template,
        input=request.input,
        previous=text_output,
        context=context,
        step_index=step.number,
        step_name=step.name,
        step_inputs=step_inputs,
        step_outputs=step_outputs,
        variables=variables,
    )


def _emit_summary_from_output(
    bus: Optional[EventBus],
    step_dir: Path,
    output_file: str,
    step_number: int,
    invocation: int,
    kind: str,
) -> None:
    """Read the runner's ``output.json`` and emit a `summary` event.

    Each "side-effect" step type (write_context, image_prompt, save_wildcard,
    create_ticket) writes a small JSON describing what it did; we synthesize a
    one-line caption from those fields and put the full payload in `detail` so
    the timeline node can render rich content if desired.
    """
    if bus is None:
        return
    try:
        data = json.loads((step_dir / output_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if kind == "write_context":
        title = data.get("title") or ""
        summary = f"Saved to context: {title}" if title else "Wrote context item"
    elif kind == "image_prompt":
        name = data.get("name") or ""
        summary = f"Saved image prompt: {name}" if name else "Saved image prompt"
    elif kind == "save_wildcard":
        action = data.get("action") or "save"
        wc = data.get("wildcard") or {}
        name = wc.get("name") or ""
        summary = f"Wildcard {action}: {name}" if name else f"Wildcard {action}"
    elif kind == "create_ticket":
        title = data.get("title") or ""
        summary = f"Created ticket: {title}" if title else "Created ticket"
    else:
        summary = kind
    bus.emit("summary", step_number=step_number, invocation=invocation,
             kind=kind, summary=summary, detail=data)


async def execute_chain_job(
    job_id: str,
    job_dir: Path,
    request: ChainJobRequest,
    event_bus: Optional[EventBus] = None,
) -> None:
    from .sequences import list_sequences

    steps_dir = job_dir / "steps"
    steps_dir.mkdir(exist_ok=True)

    seq_map = {s["id"]: s for s in list_sequences()}
    start_ts_mono = datetime.now(timezone.utc)

    def _emit(event_type: str, **payload: Any) -> None:
        if event_bus is not None:
            event_bus.emit(event_type, **payload)

    # Ensure top-level steps carry positive unique numbers, then expand sequences inline.
    try:
        _renumber_top_level(list(request.steps))
        flat_steps = _expand_steps(list(request.steps), seq_map)
    except (RuntimeError, ValueError) as exc:
        _write_chain_status(job_dir, "error", error=str(exc))
        _append_log(job_dir, f"[expansion error] {exc}\n")
        _emit("job_done", status="error", error=str(exc), final_output=None, artifacts=[],
              duration_ms=int((datetime.now(timezone.utc) - start_ts_mono).total_seconds() * 1000))
        return

    if not flat_steps:
        _write_chain_status(job_dir, "error", error="no steps after expansion")
        _append_log(job_dir, "[expansion error] no steps after expansion\n")
        _emit("job_done", status="error", error="no steps after expansion", final_output=None,
              artifacts=[],
              duration_ms=int((datetime.now(timezone.utc) - start_ts_mono).total_seconds() * 1000))
        return

    step_by_number: dict[int, ChainStep] = {s.number: s for s in flat_steps}
    order: list[int] = sorted(step_by_number.keys())
    step_count = len(order)
    _write_chain_status(
        job_dir, "running",
        step_count=step_count,
        progress=0.0,
        current_step_index=None,
        current_step_id=None,
        current_step_name=None,
    )
    _append_log(job_dir, f"[start] chain job {job_id} with {step_count} steps\n")
    _emit("job_start", job_id=job_id, step_count=step_count)

    client = OpenAICompatibleLLMClient()
    text_output = request.input
    variables = _resolve_variables(request)
    step_inputs: dict[int, list[str]] = {n: [] for n in order}
    step_outputs: dict[int, list[str]] = {n: [] for n in order}
    visits: dict[int, int] = {n: 0 for n in order}
    invocation_counter: dict[int, int] = {n: 0 for n in order}
    current_preset_name: Optional[str] = None
    executed_step_dirs: list[tuple[str, str]] = []
    total_runs_executed = 0
    MAX_TOTAL_RUNS = 2000

    def _next_in_order(ptr: int) -> Optional[int]:
        try:
            idx = order.index(ptr)
        except ValueError:
            return None
        return order[idx + 1] if idx + 1 < len(order) else None

    ptr: Optional[int] = order[0]
    while ptr is not None:
        step = step_by_number.get(ptr)
        if step is None:
            err = f"goto target step {ptr} does not exist"
            _write_chain_status(job_dir, "error", error=err)
            _append_log(job_dir, f"[error] {err}\n")
            return

        visits[ptr] += 1
        if visits[ptr] > step.visit_cap:
            err = f"step {ptr} ({step.name}) exceeded visit_cap={step.visit_cap}"
            _write_chain_status(job_dir, "error", error=err)
            _append_log(job_dir, f"[error] {err}\n")
            return
        total_runs_executed += 1
        if total_runs_executed > MAX_TOTAL_RUNS:
            err = f"chain exceeded total run budget ({MAX_TOTAL_RUNS}) — likely runaway goto"
            _write_chain_status(job_dir, "error", error=err)
            _append_log(job_dir, f"[error] {err}\n")
            return

        alt = _pick_alternative(step)

        if step.type == "goto":
            if alt.fall_through:
                _append_log(
                    job_dir,
                    f"[goto step {ptr}] fall_through (weights chose alt with fall_through)\n",
                )
                _emit("goto", from_step=ptr, target_step=None, fall_through=True)
                ptr = _next_in_order(ptr)
            else:
                _append_log(
                    job_dir,
                    f"[goto step {ptr}] jump → step {alt.target_step}\n",
                )
                _emit("goto", from_step=ptr, target_step=alt.target_step, fall_through=False)
                ptr = alt.target_step
            continue

        inv = invocation_counter[ptr]
        invocation_counter[ptr] += 1
        raw_id = step.id or step.name or f"step_{ptr}"
        step_id = _sanitize_id(raw_id, f"step_{ptr}")
        step_dir_name = (
            f"{ptr:03d}_{step_id}" if inv == 0 else f"{ptr:03d}_{step_id}_x{inv:02d}"
        )
        step_dir = steps_dir / step_dir_name
        step_dir.mkdir(exist_ok=True)
        executed_step_dirs.append((step_dir_name, step.type))

        # Progress is approximate: how many distinct steps have been touched at least once.
        touched = sum(1 for n in order if visits[n] > 0)
        _write_chain_status(
            job_dir, "running",
            step_count=step_count,
            progress=touched / step_count if step_count else 0.0,
            current_step_index=ptr,
            current_step_id=step_id,
            current_step_name=step.name,
        )

        step_started_at = _now_iso()
        _write_step_status(
            step_dir,
            id=step_id, name=step.name, type=step.type,
            status="running", started_at=step_started_at,
            step_number=ptr, invocation=inv,
        )
        alt_index = step.alternatives.index(alt) if alt in step.alternatives else 0
        _emit(
            "step_start",
            step_number=ptr, invocation=inv, step_id=step_id,
            name=step.name, step_type=step.type, alt_index=alt_index,
        )

        try:
            if step.type == "llm":
                from .llm_swap import ensure_loaded_for_step
                from .steps.llm import run_llm_step

                effective_llm, current_preset_name, swap_log = await ensure_loaded_for_step(
                    step, alt, request.llm, current_preset_name
                )
                if swap_log is not None:
                    _append_log(job_dir, f"[step {ptr} inv {inv}] {swap_log}\n")
                # Reasoning control is a per-request budget (no model reload):
                # 0 ends thinking immediately, -1 leaves it unrestricted. Honored
                # only when the server was launched without a --reasoning-budget.
                thinking = alt.thinking if alt.thinking is not None else DEFAULT_THINKING
                effective_llm = effective_llm.model_copy(
                    update={"thinking_budget_tokens": -1 if thinking else 0}
                )
                request_for_step = request.model_copy(update={"llm": effective_llm})
                new_output, output_file, rendered_prompt = await run_llm_step(
                    step_dir, step, alt, request_for_step, client, text_output, ptr,
                    step_inputs=step_inputs,
                    step_outputs=step_outputs,
                    variables=variables,
                    event_bus=event_bus,
                    job_id=job_id,
                    invocation=inv,
                )
                step_inputs[ptr].append(rendered_prompt)
                step_outputs[ptr].append(new_output)
                text_output = new_output
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file, tools=alt.tools,
                    step_number=ptr, invocation=inv,
                )
                _append_log(job_dir, f"[step {ptr} inv {inv}] llm done: {step_id}\n")
                _emit(
                    "step_done",
                    step_number=ptr, invocation=inv, status="done",
                    output_file=f"steps/{step_dir_name}/{output_file}",
                    full_text=new_output,
                )

            elif step.type == "voice":
                from .steps.voice import run_voice_step
                rendered_prompt = _render(
                    alt.prompt, request=request, text_output=text_output, context="",
                    step=step, step_inputs=step_inputs, step_outputs=step_outputs, variables=variables,
                )
                voice_pre = _render(
                    alt.voice_pre or "", request=request, text_output=text_output, context="",
                    step=step, step_inputs=step_inputs, step_outputs=step_outputs, variables=variables,
                )
                voice_post = _render(
                    alt.voice_post or "", request=request, text_output=text_output, context="",
                    step=step, step_inputs=step_inputs, step_outputs=step_outputs, variables=variables,
                )
                step_inputs[ptr].append(rendered_prompt or text_output)
                speak_text = rendered_prompt.strip() or text_output
                _emit("step_input", step_number=ptr, invocation=inv,
                      rendered_prompt=speak_text)
                output_file = await run_voice_step(
                    step_dir, step, alt, speak_text, client=client, llm_config=request.llm,
                    event_bus=event_bus, job_id=job_id, step_number=ptr, invocation=inv,
                    step_dir_name=step_dir_name, voice_pre=voice_pre, voice_post=voice_post,
                )
                step_outputs[ptr].append("")
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file, step_number=ptr, invocation=inv,
                )
                _append_log(job_dir, f"[step {ptr} inv {inv}] voice done: {step_id}\n")
                _emit(
                    "step_done",
                    step_number=ptr, invocation=inv, status="done",
                    output_file=f"steps/{step_dir_name}/{output_file}",
                )

            elif step.type == "write_context":
                from .steps.write_context import run_write_context_step
                ctx_pre = _render(
                    alt.ctx_pre or "", request=request, text_output=text_output, context="",
                    step=step, step_inputs=step_inputs, step_outputs=step_outputs, variables=variables,
                )
                ctx_post = _render(
                    alt.ctx_post or "", request=request, text_output=text_output, context="",
                    step=step, step_inputs=step_inputs, step_outputs=step_outputs, variables=variables,
                )
                step_inputs[ptr].append(text_output)
                _emit("step_input", step_number=ptr, invocation=inv,
                      rendered_prompt=text_output)
                output_file = run_write_context_step(
                    step_dir, step, alt, text_output, ctx_pre=ctx_pre, ctx_post=ctx_post
                )
                step_outputs[ptr].append("")
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file, step_number=ptr, invocation=inv,
                )
                _append_log(job_dir, f"[step {ptr} inv {inv}] write_context done: {step_id}\n")
                _emit_summary_from_output(
                    event_bus, step_dir, output_file, ptr, inv, "write_context",
                )
                _emit(
                    "step_done",
                    step_number=ptr, invocation=inv, status="done",
                    output_file=f"steps/{step_dir_name}/{output_file}",
                )

            elif step.type == "image_prompt":
                from .steps.image_prompt import run_image_prompt_step
                rendered_name = _render(
                    alt.image_prompt_name or "", request=request, text_output=text_output,
                    context="", step=step, step_inputs=step_inputs, step_outputs=step_outputs,
                    variables=variables,
                )
                rendered_body = _render(
                    alt.prompt, request=request, text_output=text_output, context="",
                    step=step, step_inputs=step_inputs, step_outputs=step_outputs,
                    variables=variables,
                )
                step_inputs[ptr].append(rendered_body or text_output)
                _emit("step_input", step_number=ptr, invocation=inv,
                      rendered_prompt=rendered_body or text_output)
                output_file = run_image_prompt_step(
                    step_dir, step, alt, rendered_name, rendered_body, text_output
                )
                step_outputs[ptr].append(rendered_name)
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file, step_number=ptr, invocation=inv,
                )
                _append_log(job_dir, f"[step {ptr} inv {inv}] image_prompt done: {step_id}\n")
                _emit_summary_from_output(
                    event_bus, step_dir, output_file, ptr, inv, "image_prompt",
                )
                _emit(
                    "step_done",
                    step_number=ptr, invocation=inv, status="done",
                    output_file=f"steps/{step_dir_name}/{output_file}",
                )

            elif step.type == "save_wildcard":
                from .steps.save_wildcard import run_save_wildcard_step
                rendered_name = _render(
                    alt.wildcard_name or "", request=request, text_output=text_output,
                    context="", step=step, step_inputs=step_inputs, step_outputs=step_outputs,
                    variables=variables,
                )
                rendered_body = _render(
                    alt.prompt, request=request, text_output=text_output, context="",
                    step=step, step_inputs=step_inputs, step_outputs=step_outputs,
                    variables=variables,
                )
                step_inputs[ptr].append(rendered_body or text_output)
                _emit("step_input", step_number=ptr, invocation=inv,
                      rendered_prompt=rendered_body or text_output)
                output_file = run_save_wildcard_step(
                    step_dir, step, alt, rendered_name, rendered_body, text_output
                )
                step_outputs[ptr].append(rendered_name)
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file, step_number=ptr, invocation=inv,
                )
                _append_log(job_dir, f"[step {ptr} inv {inv}] save_wildcard done: {step_id}\n")
                _emit_summary_from_output(
                    event_bus, step_dir, output_file, ptr, inv, "save_wildcard",
                )
                _emit(
                    "step_done",
                    step_number=ptr, invocation=inv, status="done",
                    output_file=f"steps/{step_dir_name}/{output_file}",
                )

            elif step.type == "create_ticket":
                from .steps.create_ticket import run_create_ticket_step
                rendered_title = _render(
                    alt.ticket_title_template or "", request=request, text_output=text_output,
                    context="", step=step, step_inputs=step_inputs, step_outputs=step_outputs,
                    variables=variables,
                )
                rendered_desc = _render(
                    alt.ticket_description_template or "", request=request, text_output=text_output,
                    context="", step=step, step_inputs=step_inputs, step_outputs=step_outputs,
                    variables=variables,
                )
                step_inputs[ptr].append(rendered_title)
                _emit("step_input", step_number=ptr, invocation=inv,
                      rendered_prompt=rendered_title)
                output_file = run_create_ticket_step(
                    step_dir, step, alt, rendered_title, rendered_desc, text_output
                )
                step_outputs[ptr].append(rendered_title)
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file, step_number=ptr, invocation=inv,
                )
                _append_log(job_dir, f"[step {ptr} inv {inv}] create_ticket done: {step_id}\n")
                _emit_summary_from_output(
                    event_bus, step_dir, output_file, ptr, inv, "create_ticket",
                )
                _emit(
                    "step_done",
                    step_number=ptr, invocation=inv, status="done",
                    output_file=f"steps/{step_dir_name}/{output_file}",
                )

            else:
                err = f"unsupported step type {step.type!r}"
                raise RuntimeError(err)

        except Exception as exc:
            _write_step_status(
                step_dir,
                id=step_id, name=step.name, type=step.type,
                status="error", started_at=step_started_at, completed_at=_now_iso(),
                error=str(exc), step_number=ptr, invocation=inv,
            )
            _write_chain_status(job_dir, "error", error=str(exc))
            _append_log(job_dir, f"[step {ptr} inv {inv}] error: {exc}\n")
            _emit("step_error", step_number=ptr, invocation=inv, error=str(exc))
            _emit("job_done", status="error", error=str(exc), final_output=None,
                  artifacts=[],
                  duration_ms=int((datetime.now(timezone.utc) - start_ts_mono).total_seconds() * 1000))
            return

        ptr = _next_in_order(ptr)

    (job_dir / "final_output.txt").write_text(text_output, encoding="utf-8")

    artifacts = []
    for step_dir_name, step_type in executed_step_dirs:
        if step_type == "llm":
            output_path = job_dir / "steps" / step_dir_name / "output.txt"
            if output_path.exists():
                artifacts.append({
                    "filename": f"steps/{step_dir_name}/output.txt",
                    "size": output_path.stat().st_size,
                    "created_at": _now_iso(),
                })
        elif step_type == "voice":
            for ext in ("wav", "mp3", "ogg"):
                output_path = job_dir / "steps" / step_dir_name / f"output.{ext}"
                if output_path.exists():
                    artifacts.append({
                        "filename": f"steps/{step_dir_name}/output.{ext}",
                        "size": output_path.stat().st_size,
                        "created_at": _now_iso(),
                    })
                    break
        elif step_type in ("write_context", "image_prompt", "save_wildcard", "create_ticket"):
            output_path = job_dir / "steps" / step_dir_name / "output.json"
            if output_path.exists():
                artifacts.append({
                    "filename": f"steps/{step_dir_name}/output.json",
                    "size": output_path.stat().st_size,
                    "created_at": _now_iso(),
                })
    final_path = job_dir / "final_output.txt"
    artifacts.append({
        "filename": "final_output.txt",
        "size": final_path.stat().st_size,
        "created_at": _now_iso(),
    })
    (job_dir / "artifacts.json").write_text(json.dumps(artifacts, indent=2), encoding="utf-8")

    _write_chain_status(
        job_dir, "done",
        step_count=step_count,
        progress=1.0,
        current_step_index=step_count,
        current_step_id=None,
        current_step_name=None,
        outputs={"final_output": "final_output.txt"},
    )
    _append_log(job_dir, f"[done] chain job {job_id} completed\n")
    _emit(
        "job_done",
        status="done",
        final_output=text_output,
        artifacts=artifacts,
        duration_ms=int((datetime.now(timezone.utc) - start_ts_mono).total_seconds() * 1000),
    )
