from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .llm_client import OpenAICompatibleLLMClient
from .models import ChainJobRequest, ChainStep


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
    prefix: str = "",
    depth: int = 0,
) -> list[ChainStep]:
    if depth > 20:
        raise RuntimeError("Sequence expansion depth exceeded 20 — possible cycle not caught at save time")
    import copy
    result: list[ChainStep] = []
    for step in steps:
        if step.type != "sequence":
            if prefix:
                step = copy.copy(step)
                step.name = f"{prefix} > {step.name}"
            result.append(step)
        else:
            if not step.sequence_id:
                raise RuntimeError(f"Sequence step '{step.name}' has no sequence_id")
            seq = seq_map.get(step.sequence_id)
            if seq is None:
                raise RuntimeError(f"Sequence step '{step.name}' references unknown sequence id '{step.sequence_id}'")
            new_prefix = f"{prefix} > {step.name}" if prefix else step.name
            sub_steps = [ChainStep(**s) for s in seq.get("steps", [])]
            result.extend(_expand_steps(sub_steps, seq_map, new_prefix, depth + 1))
    return result


async def execute_chain_job(
    job_id: str,
    job_dir: Path,
    request: ChainJobRequest,
) -> None:
    from .sequences import list_sequences
    from .steps.llm import run_llm_step
    from .steps.voice import run_voice_step
    from .steps.write_context import run_write_context_step

    steps_dir = job_dir / "steps"
    steps_dir.mkdir(exist_ok=True)

    seq_map = {s["id"]: s for s in list_sequences()}
    try:
        flat_steps = _expand_steps(list(request.steps), seq_map)
    except RuntimeError as exc:
        _write_chain_status(job_dir, "error", error=str(exc))
        _append_log(job_dir, f"[expansion error] {exc}\n")
        return

    step_count = len(flat_steps)
    _write_chain_status(
        job_dir, "running",
        step_count=step_count,
        progress=0.0,
        current_step_index=None,
        current_step_id=None,
        current_step_name=None,
    )
    _append_log(job_dir, f"[start] chain job {job_id} with {step_count} steps\n")

    client = OpenAICompatibleLLMClient()
    text_output = request.input
    executed_step_dirs: list[tuple[str, str]] = []  # (dir_name, step_type)
    current_preset_name: Optional[str] = None

    for i, step in enumerate(flat_steps):
        step_index = i + 1
        raw_id = step.id or step.name or f"step_{step_index}"
        step_id = _sanitize_id(raw_id, f"step_{step_index}")
        step_dir_name = f"{step_index:03d}_{step_id}"
        step_dir = steps_dir / step_dir_name
        step_dir.mkdir(exist_ok=True)
        executed_step_dirs.append((step_dir_name, step.type))

        _write_chain_status(
            job_dir, "running",
            step_count=step_count,
            progress=i / step_count,
            current_step_index=step_index,
            current_step_id=step_id,
            current_step_name=step.name,
        )

        step_started_at = _now_iso()
        _write_step_status(
            step_dir,
            id=step_id, name=step.name, type=step.type,
            status="running", started_at=step_started_at,
        )

        if step.type == "llm":
            try:
                from .llm_swap import ensure_loaded_for_step
                effective_llm, current_preset_name, swap_log = await ensure_loaded_for_step(
                    step, request.llm, current_preset_name
                )
                if swap_log is not None:
                    _append_log(job_dir, f"[step {step_index}/{step_count}] {swap_log}\n")
                request_for_step = request.model_copy(update={"llm": effective_llm})
                text_output, output_file = await run_llm_step(
                    step_dir, step, request_for_step, client, text_output, step_index
                )
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file, tools=step.tools,
                )
                _append_log(job_dir, f"[step {step_index}/{step_count}] llm done: {step_id}\n")
            except Exception as exc:
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="error", started_at=step_started_at, completed_at=_now_iso(),
                    error=str(exc), tools=step.tools,
                )
                _write_chain_status(job_dir, "error", error=str(exc))
                _append_log(job_dir, f"[step {step_index}/{step_count}] error: {exc}\n")
                return

        elif step.type == "voice":
            try:
                output_file = await run_voice_step(
                    step_dir, step, text_output, client=client, llm_config=request.llm
                )
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file,
                )
                _append_log(job_dir, f"[step {step_index}/{step_count}] voice done: {step_id}\n")
                # text_output intentionally unchanged
            except Exception as exc:
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="error", started_at=step_started_at, completed_at=_now_iso(),
                    error=str(exc),
                )
                _write_chain_status(job_dir, "error", error=str(exc))
                _append_log(job_dir, f"[step {step_index}/{step_count}] error: {exc}\n")
                return

        elif step.type == "write_context":
            try:
                output_file = run_write_context_step(step_dir, step, text_output)
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="done", started_at=step_started_at, completed_at=_now_iso(),
                    output_file=output_file,
                )
                _append_log(job_dir, f"[step {step_index}/{step_count}] write_context done: {step_id}\n")
                # text_output intentionally unchanged
            except Exception as exc:
                _write_step_status(
                    step_dir,
                    id=step_id, name=step.name, type=step.type,
                    status="error", started_at=step_started_at, completed_at=_now_iso(),
                    error=str(exc),
                )
                _write_chain_status(job_dir, "error", error=str(exc))
                _append_log(job_dir, f"[step {step_index}/{step_count}] error: {exc}\n")
                return

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
        elif step_type == "write_context":
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
