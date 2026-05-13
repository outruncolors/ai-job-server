from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .client import ComfyUIClient
from .config import ComfyUIConfig
from .manager import ComfyUIManager
from .workflows import inject_params, load_workflow


def _write_status(job_dir: Path, status: str, *, error: str | None = None) -> None:
    from ..jobs import _write_status as _jobs_write_status
    _jobs_write_status(job_dir, status, error=error)


def _update_artifacts(job_dir: Path, output_path: Path) -> None:
    from ..jobs import _update_artifacts as _jobs_update_artifacts
    _jobs_update_artifacts(job_dir, output_path)


def _append_log(job_dir: Path, text: str) -> None:
    from ..jobs import _append_log as _jobs_append_log
    _jobs_append_log(job_dir, text)


async def execute_image_job(
    job_id: str,
    job_dir: Path,
    request: Any,
    config: ComfyUIConfig,
    manager: ComfyUIManager,
) -> None:
    """Execute an image generation job via ComfyUI."""
    _write_status(job_dir, "running")
    _append_log(job_dir, f"[start] workflow={request.workflow}\n")

    try:
        if not await manager._is_alive():
            if config.autostart:
                _append_log(job_dir, "[start] ComfyUI not running — starting...\n")
                await manager.start()
            else:
                raise RuntimeError(
                    "ComfyUI is not running. Start it from the Image > Server tab."
                )

        workflow = load_workflow(request.workflow)
        workflow = inject_params(workflow, request.params)

        client = ComfyUIClient(f"http://{config.host}:{config.port}")

        # Write the resolved workflow to job_dir for audit
        (job_dir / "workflow.json").write_text(
            json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        submission = await client.submit(workflow, client_id=job_id)
        prompt_id: str = submission["prompt_id"]
        _append_log(job_dir, f"[submitted] prompt_id={prompt_id}\n")

        if submission.get("node_errors"):
            errs = json.dumps(submission["node_errors"])
            _append_log(job_dir, f"[node_errors] {errs}\n")

        # Poll /history until our prompt appears
        poll_interval = 1.0
        max_wait = 600.0  # 10-minute cap
        elapsed = 0.0
        outputs: dict[str, Any] = {}

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            history = await client.history(prompt_id)
            if prompt_id in history:
                entry = history[prompt_id]
                outputs = entry.get("outputs", {})
                status_info = entry.get("status", {})
                if status_info.get("status_str") == "error":
                    msgs = status_info.get("messages", [])
                    raise RuntimeError(f"ComfyUI reported error: {msgs}")
                break

        if not outputs:
            raise RuntimeError(f"Timed out waiting for ComfyUI prompt {prompt_id}")

        # Fetch each output image and save to job_dir
        fetched: list[str] = []
        for node_id, node_out in outputs.items():
            for img in node_out.get("images", []):
                filename: str = img["filename"]
                subfolder: str = img.get("subfolder", "")
                img_type: str = img.get("type", "output")
                data = await client.fetch_view(filename, subfolder, img_type)
                dest = job_dir / filename
                dest.write_bytes(data)
                _update_artifacts(job_dir, dest)
                fetched.append(filename)
                _append_log(job_dir, f"[output] {filename} ({len(data)} bytes)\n")

        if not fetched:
            raise RuntimeError("ComfyUI completed but returned no output images")

        _write_status(job_dir, "done")
        _append_log(job_dir, f"[done] {len(fetched)} image(s) saved\n")

    except Exception as exc:
        _write_status(job_dir, "error", error=str(exc))
        _append_log(job_dir, f"[error] {exc}\n")
