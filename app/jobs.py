from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

JOBS_BASE = Path(os.environ.get("JOBS_BASE", "/srv/ai-jobs"))


def _today_dir() -> Path:
    return JOBS_BASE / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def find_job_dir(job_id: str) -> Optional[Path]:
    """Search all date directories for a job_id."""
    if not JOBS_BASE.exists():
        return None
    for date_dir in sorted(JOBS_BASE.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        job_dir = date_dir / job_id
        if job_dir.is_dir():
            return job_dir
    return None


def create_job(job_type: str, request_data: dict[str, Any], input_text: str) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    job_dir = _today_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "queued",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "error": None,
    }

    (job_dir / "request.json").write_text(
        json.dumps({"job_type": job_type, "requested": request_data}, indent=2),
        encoding="utf-8",
    )
    (job_dir / "input.txt").write_text(input_text, encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    (job_dir / "logs.txt").write_text("", encoding="utf-8")
    (job_dir / "artifacts.json").write_text("[]", encoding="utf-8")

    return status


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    job_dir = find_job_dir(job_id)
    if job_dir is None:
        return None
    status_file = job_dir / "status.json"
    if not status_file.exists():
        return None
    return json.loads(status_file.read_text(encoding="utf-8"))


def list_jobs() -> list[dict[str, Any]]:
    if not JOBS_BASE.exists():
        return []
    jobs = []
    for date_dir in sorted(JOBS_BASE.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for job_dir in sorted(date_dir.iterdir(), reverse=True):
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if status_file.exists():
                jobs.append(json.loads(status_file.read_text(encoding="utf-8")))
    return jobs


def clear_pending_jobs() -> int:
    import shutil
    if not JOBS_BASE.exists():
        return 0
    removed = 0
    for date_dir in JOBS_BASE.iterdir():
        if not date_dir.is_dir():
            continue
        for job_dir in date_dir.iterdir():
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if not status_file.exists():
                continue
            status = json.loads(status_file.read_text(encoding="utf-8"))
            if status.get("status") == "queued":
                shutil.rmtree(job_dir)
                removed += 1
    return removed


def get_job_file(job_id: str, filename: str) -> Optional[Path]:
    job_dir = find_job_dir(job_id)
    if job_dir is None:
        return None
    target = (job_dir / filename).resolve()
    if not str(target).startswith(str(job_dir.resolve())):
        return None
    if not target.exists() or target.is_dir():
        return None
    return target


# ---------------------------------------------------------------------------
# Private helpers for execute_voice_job
# ---------------------------------------------------------------------------

def _write_status(
    job_dir: Path,
    status: str,
    *,
    error: Optional[str] = None,
) -> None:
    status_file = job_dir / "status.json"
    data = json.loads(status_file.read_text(encoding="utf-8"))
    data["status"] = status
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    if error is not None:
        data["error"] = error
    status_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _update_artifacts(job_dir: Path, output_path: Path) -> None:
    if not output_path.exists():
        return
    artifacts_file = job_dir / "artifacts.json"
    artifacts = json.loads(artifacts_file.read_text(encoding="utf-8"))
    artifacts.append({
        "filename": output_path.name,
        "size": output_path.stat().st_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    artifacts_file.write_text(json.dumps(artifacts, indent=2), encoding="utf-8")


def _append_log(job_dir: Path, text: str) -> None:
    with (job_dir / "logs.txt").open("a", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# Voice job execution (framework-independent)
# ---------------------------------------------------------------------------

async def execute_voice_job(
    job_id: str,
    job_dir: Path,
    request: Any,
    config: Any,
    manager: Any,
) -> None:
    """Execute a voice synthesis job. Accepts plain arguments; no FastAPI deps."""
    from .omnivoice.client import OmniVoicePersistentClient
    from .omnivoice.runner import OmniVoiceEphemeralRunner

    mode = request.mode or config.mode
    output_path = job_dir / f"output.{config.response_format}"

    # Resolve and persist effective settings before synthesis
    effective: dict[str, Any] = {
        "mode": mode,
        "model": config.model,
        "voice": request.voice,
        "speed": request.speed,
        "language": request.language or config.language,
        "response_format": config.response_format,
        "num_step": request.num_step,
        "guidance_scale": request.guidance_scale,
        "voice_preset_id": request.voice_preset_id,
    }
    if mode == "persistent":
        effective["persistent_api_base"] = config.persistent_api_base
    else:
        effective["infer_base_command"] = config.infer_base_command or ["omnivoice-infer"]

    req_file = job_dir / "request.json"
    req_data = json.loads(req_file.read_text(encoding="utf-8"))
    req_data["effective"] = effective
    req_file.write_text(json.dumps(req_data, indent=2), encoding="utf-8")

    _write_status(job_dir, "running")
    _append_log(job_dir, f"[start] mode={mode} voice={request.voice}\n")

    manager.active_voice_jobs += 1
    try:
        if mode == "persistent":
            client = OmniVoicePersistentClient(config.persistent_api_base)
            await client.synthesize(
                request.text,
                output_path,
                model=config.model,
                voice=request.voice,
                response_format=config.response_format,
                speed=request.speed,
                language=request.language or config.language,
            )
        else:
            if mode == "persistent" and request.voice_preset_id:
                _append_log(job_dir, "[warn] voice_preset_id is ignored in persistent mode\n")

            ref_audio_filename: Optional[str] = None
            ref_text_resolved: Optional[str] = request.ref_text

            if mode != "persistent" and request.voice_preset_id:
                from .voice_presets import get_preset, resolve_preset_wav
                preset = get_preset(request.voice_preset_id)
                if preset is None:
                    raise RuntimeError(
                        f"Voice preset {request.voice_preset_id!r} not found"
                    )
                wav_path = resolve_preset_wav(request.voice_preset_id)
                if wav_path is None:
                    raise RuntimeError(
                        f"Voice preset {preset['name']!r} wav file missing "
                        f"(was {preset['wav_filename']}). Re-upload or remove the preset."
                    )
                ref_audio_filename = str(wav_path)
                ref_text_resolved = preset["caption"]

            runner = OmniVoiceEphemeralRunner(config)
            await runner.run(
                request.text,
                output_path,
                job_dir,
                language=request.language,
                instruct=request.instruct,
                ref_audio_filename=ref_audio_filename,
                ref_text=ref_text_resolved,
                num_step=request.num_step,
                guidance_scale=request.guidance_scale,
            )
        _update_artifacts(job_dir, output_path)
        _write_status(job_dir, "done")
        _append_log(job_dir, f"[done] output written to {output_path.name}\n")
    except Exception as exc:
        _write_status(job_dir, "error", error=str(exc))
        _append_log(job_dir, f"[error] {exc}\n")
    finally:
        manager.active_voice_jobs -= 1
