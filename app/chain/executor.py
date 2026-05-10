from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .llm_client import OpenAICompatibleLLMClient
from .models import ChainJobRequest


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
) -> None:
    data = {
        "id": id,
        "name": name,
        "type": type,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "error": error,
        "output_file": output_file,
    }
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


async def execute_chain_job(
    job_id: str,
    job_dir: Path,
    request: ChainJobRequest,
) -> None:
    from .context import resolve_context_files
    from .template import render_template

    steps_dir = job_dir / "steps"
    steps_dir.mkdir(exist_ok=True)

    step_count = len(request.steps)
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
    previous_output = request.input
    executed_step_dirs: list[str] = []

    for i, step in enumerate(request.steps):
        step_index = i + 1
        raw_id = step.id or step.name or f"step_{step_index}"
        step_id = _sanitize_id(raw_id, f"step_{step_index}")
        step_dir_name = f"{step_index:03d}_{step_id}"
        step_dir = steps_dir / step_dir_name
        step_dir.mkdir(exist_ok=True)
        executed_step_dirs.append(step_dir_name)

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
            id=step_id,
            name=step.name,
            type=step.type,
            status="running",
            started_at=step_started_at,
        )
        (step_dir / "request.json").write_text(
            json.dumps(step.model_dump(), indent=2), encoding="utf-8"
        )

        try:
            context = resolve_context_files(step.context_files)
            (step_dir / "context.txt").write_text(context, encoding="utf-8")

            prompt = render_template(
                step.prompt,
                input=request.input,
                previous=previous_output,
                context=context,
                step_index=step_index,
                step_name=step.name,
            )
            (step_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

            output = await client.generate(prompt, request.llm)
            (step_dir / "output.txt").write_text(output, encoding="utf-8")

            _write_step_status(
                step_dir,
                id=step_id,
                name=step.name,
                type=step.type,
                status="done",
                started_at=step_started_at,
                completed_at=_now_iso(),
                output_file="output.txt",
            )
            _append_log(job_dir, f"[step {step_index}/{step_count}] done: {step_id}\n")
            previous_output = output

        except Exception as exc:
            _write_step_status(
                step_dir,
                id=step_id,
                name=step.name,
                type=step.type,
                status="error",
                started_at=step_started_at,
                completed_at=_now_iso(),
                error=str(exc),
            )
            _write_chain_status(job_dir, "error", error=str(exc))
            _append_log(job_dir, f"[step {step_index}/{step_count}] error: {exc}\n")
            return

    (job_dir / "final_output.txt").write_text(previous_output, encoding="utf-8")

    artifacts = []
    for step_dir_name in executed_step_dirs:
        output_path = job_dir / "steps" / step_dir_name / "output.txt"
        if output_path.exists():
            artifacts.append({
                "filename": f"steps/{step_dir_name}/output.txt",
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
