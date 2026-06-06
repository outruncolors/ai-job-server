"""JobQueue runners for Vision and Speech-to-Text jobs.

These mirror :func:`app.comfyui.runner.execute_image_job` /
:func:`app.jobs.execute_voice_job`: they own the on-disk ``status.json`` /
``logs.txt`` / ``artifacts.json`` lifecycle and never raise (the queue worker
logs but does not act on exceptions). The actual model swap + inference lives in
``service.run_vision`` / ``service.run_stt`` (called here, unchanged); the result
text is written to ``output.txt`` — the result artifact, consistent with
``output.wav`` for voice.

The uploaded input file was saved into ``job_dir`` by the route (and persists
across restarts), so a recovered job re-reads it and re-runs correctly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..jobs import _append_log, _update_artifacts, _write_status
from .service import (
    VISION_NATIVE_MIMES,
    run_stt,
    run_vision,
    transcode_image_to_png,
    transcode_to_wav,
)


async def execute_vision_job(job_id: str, job_dir: Path, request: Any) -> None:
    """Answer ``request.prompt`` about the saved image. Writes ``output.txt``."""
    _write_status(job_dir, "running")
    _append_log(job_dir, "[start] vision\n")

    try:
        image_bytes = (job_dir / request.input_filename).read_bytes()
        mime = (request.mime or "").lower()
        # llama.cpp's image loader can't decode webp (and friends) — transcode to
        # PNG first, or the model server 400s on "failed to load image".
        if mime not in VISION_NATIVE_MIMES:
            _append_log(job_dir, f"[vision] converting {mime or 'image'} → image/png (ffmpeg)…\n")
            image_bytes = await transcode_image_to_png(image_bytes)
            mime = "image/png"
        _append_log(job_dir, "[swap] ensuring multimodal model is loaded…\n")
        _append_log(job_dir, "[generate] running vision inference…\n")
        text = await run_vision(image_bytes, mime, request.prompt)

        output_path = job_dir / "output.txt"
        output_path.write_text(text, encoding="utf-8")
        _update_artifacts(job_dir, output_path)
        _write_status(job_dir, "done")
        _append_log(job_dir, f"[done] wrote output.txt ({len(text)} chars)\n")
    except Exception as exc:  # noqa: BLE001 — same contract as the other runners
        _write_status(job_dir, "error", error=str(exc))
        _append_log(job_dir, f"[error] {exc}\n")


async def execute_stt_job(job_id: str, job_dir: Path, request: Any) -> None:
    """Transcribe the saved audio. Transcodes to WAV first; writes ``output.txt``."""
    _write_status(job_dir, "running")
    _append_log(job_dir, "[start] stt\n")

    try:
        raw = (job_dir / request.input_filename).read_bytes()
        _append_log(job_dir, "[stt] transcoding audio (ffmpeg)…\n")
        wav_bytes = await transcode_to_wav(raw)
        _append_log(job_dir, "[swap] ensuring multimodal model is loaded…\n")
        _append_log(job_dir, "[generate] transcribing…\n")
        text = await run_stt(wav_bytes, request.prompt)

        output_path = job_dir / "output.txt"
        output_path.write_text(text, encoding="utf-8")
        _update_artifacts(job_dir, output_path)
        _write_status(job_dir, "done")
        _append_log(job_dir, f"[done] wrote output.txt ({len(text)} chars)\n")
    except Exception as exc:  # noqa: BLE001 — same contract as the other runners
        _write_status(job_dir, "error", error=str(exc))
        _append_log(job_dir, f"[error] {exc}\n")
