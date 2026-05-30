from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any

from .client import ComfyUIClient
from .config import ComfyUIConfig
from .manager import ComfyUIManager
from .workflows import (
    find_denoise_node,
    find_image_param_nodes,
    find_seed_node,
    inject_denoise,
    inject_image_param,
    inject_prompt,
    inject_seed,
    load_workflow,
)


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
        workflow = inject_prompt(workflow, request.prompt)

        image_params: dict[str, str] = dict(getattr(request, "image_params", None) or {})
        available = find_image_param_nodes(workflow)
        # If REF_IMAGE_2 is exposed but the caller only filled REF_IMAGE_1,
        # mirror REF_IMAGE_1 into REF_IMAGE_2 so the user can drive image-edit
        # workflows with a single upload.
        if (
            "REF_IMAGE_2" in available
            and "REF_IMAGE_2" not in image_params
            and image_params.get("REF_IMAGE_1")
        ):
            image_params["REF_IMAGE_2"] = image_params["REF_IMAGE_1"]
            _append_log(
                job_dir, "[image_param] REF_IMAGE_2 mirrored from REF_IMAGE_1\n"
            )
        for title, filename in image_params.items():
            if title not in available:
                _append_log(
                    job_dir, f"[image_param] skipped {title!r} (not in workflow)\n"
                )
                continue
            workflow = inject_image_param(workflow, title, filename)
            _append_log(job_dir, f"[image_param] {title}={filename}\n")

        # DENOISE — float strength, only when the workflow exposes the node.
        denoise = getattr(request, "denoise", None)
        if denoise is not None and find_denoise_node(workflow):
            workflow = inject_denoise(workflow, float(denoise))
            _append_log(job_dir, f"[denoise] {denoise}\n")

        # SEED — randomize, explicit, or leave the workflow default in place.
        if find_seed_node(workflow):
            seed: int | None = None
            if getattr(request, "randomize_seed", False):
                seed = random.randint(0, 2**64 - 1)
            elif getattr(request, "seed", None):
                seed = int(request.seed)
            if seed is not None:
                workflow = inject_seed(workflow, seed)
                _append_log(job_dir, f"[seed] {seed}\n")

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
