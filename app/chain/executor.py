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


async def _execute_voice_step(text: str, step_dir: Path, step: ChainStep) -> str:
    from ..omnivoice.config import get_config
    from ..omnivoice.manager import get_manager
    from ..voice_presets import get_preset, resolve_preset_wav

    if not step.voice_preset_id:
        raise RuntimeError("Voice step requires a voice_preset_id")

    preset = get_preset(step.voice_preset_id)
    if preset is None:
        raise RuntimeError(f"Voice preset {step.voice_preset_id!r} not found")

    config = get_config()
    manager = get_manager()
    output_path = step_dir / f"output.{config.response_format}"

    effective: dict[str, Any] = {
        "model": config.model,
        "voice_preset_id": step.voice_preset_id,
        "voice_preset_name": preset["name"],
        "response_format": config.response_format,
    }
    (step_dir / "request.json").write_text(
        json.dumps({**step.model_dump(), "effective": effective}, indent=2), encoding="utf-8"
    )

    wav_path = resolve_preset_wav(step.voice_preset_id)
    if wav_path is None:
        raise RuntimeError(
            f"Voice preset {preset['name']!r} wav file missing. Re-upload or remove the preset."
        )

    from ..omnivoice.runner import OmniVoiceEphemeralRunner
    runner = OmniVoiceEphemeralRunner(config)
    manager.active_voice_jobs += 1
    try:
        await runner.run(
            text,
            output_path,
            step_dir,
            language=config.language,
            instruct=config.instruct,
            ref_audio_filename=str(wav_path),
            ref_text=preset["caption"],
            num_step=None,
            guidance_scale=None,
        )
    finally:
        manager.active_voice_jobs -= 1
    return output_path.name


async def execute_chain_job(
    job_id: str,
    job_dir: Path,
    request: ChainJobRequest,
) -> None:
    from .context import resolve_context_ids
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
    text_output = request.input
    executed_step_dirs: list[tuple[str, str]] = []  # (dir_name, step_type)

    for i, step in enumerate(request.steps):
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
            id=step_id,
            name=step.name,
            type=step.type,
            status="running",
            started_at=step_started_at,
        )

        if step.type == "llm":
            try:
                (step_dir / "request.json").write_text(
                    json.dumps(step.model_dump(), indent=2), encoding="utf-8"
                )
                context = resolve_context_ids(step.context_ids)
                (step_dir / "context.txt").write_text(context, encoding="utf-8")

                rendered = render_template(
                    step.prompt,
                    input=request.input,
                    previous=text_output,
                    context=context,
                    step_index=step_index,
                    step_name=step.name,
                )
                if context and "{{context}}" not in step.prompt:
                    prompt = f"<START CONTEXT>\n{context}\n<END CONTEXT>\n\n{rendered}"
                else:
                    prompt = rendered
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
                _append_log(job_dir, f"[step {step_index}/{step_count}] llm done: {step_id}\n")
                text_output = output

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

        elif step.type == "voice":
            try:
                output_filename = await _execute_voice_step(text_output, step_dir, step)
                _write_step_status(
                    step_dir,
                    id=step_id,
                    name=step.name,
                    type=step.type,
                    status="done",
                    started_at=step_started_at,
                    completed_at=_now_iso(),
                    output_file=output_filename,
                )
                _append_log(job_dir, f"[step {step_index}/{step_count}] voice done: {step_id}\n")
                # text_output intentionally unchanged

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

        elif step.type == "write_context":
            try:
                from .context_library import create_item, list_items, update_item

                parts = [p for p in [step.ctx_pre, text_output, step.ctx_post] if p]
                entry = "\n\n".join(parts)

                existing = next((item for item in list_items() if item["title"] == step.ctx_name), None)
                if existing:
                    new_content = existing["content"] + "\n\n---\n\n" + entry
                    result_item = update_item(existing["id"], content=new_content)
                else:
                    result_item = create_item(
                        title=step.ctx_name or "",
                        tags=step.ctx_tags or [],
                        description="",
                        content=entry,
                    )

                (step_dir / "output.json").write_text(
                    json.dumps(result_item, indent=2), encoding="utf-8"
                )
                _write_step_status(
                    step_dir,
                    id=step_id,
                    name=step.name,
                    type=step.type,
                    status="done",
                    started_at=step_started_at,
                    completed_at=_now_iso(),
                    output_file="output.json",
                )
                _append_log(job_dir, f"[step {step_index}/{step_count}] write_context done: {step_id}\n")
                # text_output intentionally unchanged

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
