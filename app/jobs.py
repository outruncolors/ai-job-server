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


def create_job(
    job_type: str,
    request_data: dict[str, Any],
    input_text: str,
    extra_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
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

    request_doc: dict[str, Any] = {"job_type": job_type, "requested": request_data}
    if extra_meta:
        request_doc.update(extra_meta)
    (job_dir / "request.json").write_text(
        json.dumps(request_doc, indent=2),
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


def clear_all_jobs() -> int:
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


def build_jobs_zip(job_ids: list[str], out_path: Path) -> int:
    """Zip every job's declared artifacts into out_path.

    Multi-job zips namespace entries under "<job_id>/" so files from different
    jobs can't collide. Returns the number of jobs that contributed at least
    one file.
    """
    import zipfile
    nest = len(job_ids) > 1
    count = 0
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for job_id in job_ids:
            job_dir = find_job_dir(job_id)
            if job_dir is None:
                continue
            artifacts_file = job_dir / "artifacts.json"
            if not artifacts_file.exists():
                continue
            try:
                artifacts = json.loads(artifacts_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            added = False
            job_root = job_dir.resolve()
            for a in artifacts:
                fname = a.get("filename")
                if not fname:
                    continue
                src = (job_dir / fname).resolve()
                if not str(src).startswith(str(job_root)):
                    continue
                if not src.exists() or src.is_dir():
                    continue
                arcname = f"{job_id}/{fname}" if nest else fname
                zf.write(src, arcname)
                added = True
            if added:
                count += 1
    return count


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
    from .omnivoice.runner import OmniVoiceEphemeralRunner

    output_path = job_dir / f"output.{config.response_format}"

    effective: dict[str, Any] = {
        "model": config.model,
        "voice": request.voice,
        "speed": request.speed,
        "language": request.language or config.language,
        "response_format": config.response_format,
        "num_step": request.num_step,
        "guidance_scale": request.guidance_scale,
        "voice_preset_id": request.voice_preset_id,
        "infer_base_command": config.infer_base_command or ["omnivoice-infer"],
    }

    req_file = job_dir / "request.json"
    req_data = json.loads(req_file.read_text(encoding="utf-8"))
    req_data["effective"] = effective
    req_file.write_text(json.dumps(req_data, indent=2), encoding="utf-8")

    _write_status(job_dir, "running")
    _append_log(job_dir, f"[start] voice={request.voice}\n")

    ref_audio_filename: Optional[str] = None
    ref_text_resolved: Optional[str] = request.ref_text

    if request.voice_preset_id:
        from .voice_presets import get_preset, resolve_preset_wav
        preset = get_preset(request.voice_preset_id)
        if preset is None:
            raise RuntimeError(f"Voice preset {request.voice_preset_id!r} not found")
        wav_path = resolve_preset_wav(request.voice_preset_id)
        if wav_path is None:
            raise RuntimeError(
                f"Voice preset {preset['name']!r} wav file missing "
                f"(was {preset['wav_filename']}). Re-upload or remove the preset."
            )
        ref_audio_filename = str(wav_path)
        ref_text_resolved = preset["caption"]

    common_run_kwargs = dict(
        language=request.language,
        instruct=request.instruct,
        ref_audio_filename=ref_audio_filename,
        ref_text=ref_text_resolved,
        num_step=request.num_step,
        guidance_scale=request.guidance_scale,
    )

    manager.active_voice_jobs += 1
    try:
        effective_segments = request.segments
        if request.auto_segment:
            if not request.auto_segment_llm_base_url:
                raise RuntimeError(
                    "auto_segment requires an LLM API base URL — select a preset in the Chain page"
                )
            import re
            from .chain.llm_client import OpenAICompatibleLLMClient
            from .chain.models import ChainLLMConfig
            from .chain.steps.llm import _parse_gemma_tool_calls
            from .mcp.registry import get_tool, to_openai_schema
            from .models import VoiceSegment
            from .omnivoice.constants import DEFAULT_VOICE_AUTO_SEGMENT_PROMPT

            llm_cfg = ChainLLMConfig(
                api_base=request.auto_segment_llm_base_url,
                model=request.auto_segment_llm_model,
            )
            client = OpenAICompatibleLLMClient()
            tool_def = get_tool("format_voice_segments")
            seg_prompt = config.voice_auto_segment_prompt or DEFAULT_VOICE_AUTO_SEGMENT_PROMPT
            prompt_content = f"{seg_prompt}\n\n{request.text}"
            _append_log(job_dir, "[auto-segment] calling LLM\n")

            choice = await client.chat(
                messages=[{"role": "user", "content": prompt_content}],
                llm_config=llm_cfg,
                tools=[to_openai_schema(tool_def)],
            )
            message = choice.get("message", {})
            (job_dir / "auto_segment_raw.txt").write_text(
                json.dumps(message, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            raw_tool_calls = message.get("tool_calls") or []
            if not raw_tool_calls and message.get("content"):
                raw_tool_calls = _parse_gemma_tool_calls(message["content"])

            seg_data: list[dict] = []
            if raw_tool_calls:
                args = json.loads(raw_tool_calls[0]["function"]["arguments"])
                seg_data = args.get("segments", [])
            elif message.get("content"):
                stripped = message["content"].strip()
                fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", stripped)
                if fence:
                    stripped = fence.group(1).strip()
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        seg_data = parsed
                except json.JSONDecodeError:
                    pass

            if not seg_data:
                raise RuntimeError(
                    "auto_segment: LLM did not call format_voice_segments and returned no parseable JSON"
                )
            effective_segments = [
                VoiceSegment(text=s["text"], delay_ms=int(s.get("delay_ms", 500)))
                for s in seg_data if str(s.get("text", "")).strip()
            ]
            if not effective_segments:
                raise RuntimeError("auto_segment: no non-empty segments returned by LLM")
            _append_log(job_dir, f"[auto-segment] {len(effective_segments)} segments\n")
            (job_dir / "auto_segment_segments.json").write_text(
                json.dumps(
                    [{"text": s.text, "delay_ms": s.delay_ms} for s in effective_segments],
                    indent=2, ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        runner = OmniVoiceEphemeralRunner(config)
        if effective_segments:
            from .audio_utils import merge_wav_files
            seg_paths = []
            delay_ms_list = []
            for idx, seg in enumerate(effective_segments):
                seg_path = job_dir / f"segment_{idx:03d}.wav"
                _append_log(job_dir, f"[seg {idx}] {seg.text[:60]!r}\n")
                await runner.run(seg.text, seg_path, job_dir, **common_run_kwargs)
                seg_paths.append(seg_path)
                delay_ms_list.append(seg.delay_ms)
            _append_log(job_dir, f"[merge] {len(seg_paths)} segments\n")
            merge_wav_files(seg_paths, delay_ms_list, output_path)
        else:
            await runner.run(request.text, output_path, job_dir, **common_run_kwargs)
        _update_artifacts(job_dir, output_path)
        _write_status(job_dir, "done")
        _append_log(job_dir, f"[done] output written to {output_path.name}\n")
    except Exception as exc:
        _write_status(job_dir, "error", error=str(exc))
        _append_log(job_dir, f"[error] {exc}\n")
    finally:
        manager.active_voice_jobs -= 1
