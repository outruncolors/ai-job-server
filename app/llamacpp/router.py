from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import llm_presets
from .config import LlamaCppConfig, get_config, save_config
from .manager import LlamaCppLoadError, get_manager

router = APIRouter(prefix="/v1/llamacpp", tags=["llamacpp"])


def _resolve_preset(body: dict) -> dict:
    """Accept either {"preset": <dict>} or {"preset": "<name>"}.

    A name is resolved against `app.llm_presets`; unknown names return 404 so
    callers see why the swap was rejected instead of silently falling through.
    """
    preset = body.get("preset")
    if isinstance(preset, dict):
        return preset
    if isinstance(preset, str):
        resolved = llm_presets.get_preset(preset)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"LLM preset {preset!r} not found",
            )
        return {
            "model_path": resolved["model_path"],
            "args": dict(resolved.get("args") or {}),
        }
    raise HTTPException(status_code=422, detail="missing 'preset' field")


@router.get("/status")
async def llamacpp_status() -> dict:
    return await get_manager().status()


@router.post("/start")
async def llamacpp_start(body: dict | None = None) -> dict:
    preset = None
    if body:
        try:
            preset = _resolve_preset(body)
        except HTTPException:
            # /start without a preset is allowed (adopts running process)
            if "preset" in body:
                raise
    try:
        return await get_manager().start(preset=preset)
    except LlamaCppLoadError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/stop")
async def llamacpp_stop() -> dict:
    return await get_manager().stop()


@router.post("/restart")
async def llamacpp_restart(body: dict | None = None) -> dict:
    preset = None
    if body and "preset" in body:
        preset = _resolve_preset(body)
    try:
        return await get_manager().restart(preset=preset)
    except LlamaCppLoadError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/config", response_model=LlamaCppConfig)
def llamacpp_get_config() -> LlamaCppConfig:
    return get_config()


@router.put("/config", response_model=LlamaCppConfig)
def llamacpp_put_config(new_config: LlamaCppConfig) -> LlamaCppConfig:
    save_config(new_config)
    return new_config


@router.get("/models")
def llamacpp_models() -> dict:
    cfg = get_config()
    root = Path(cfg.models_dir)
    if not root.exists():
        return {"models_dir": str(root), "models": []}
    models: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*.gguf")):
        try:
            size = p.stat().st_size
        except OSError:
            size = None
        models.append(
            {
                "path": str(p),
                "name": p.name,
                "size_bytes": size,
            }
        )
    return {"models_dir": str(root), "models": models}


@router.post("/ensure-loaded")
async def llamacpp_ensure_loaded(body: dict) -> dict:
    preset = _resolve_preset(body)
    try:
        return await get_manager().ensure_loaded(preset)
    except LlamaCppLoadError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/logs")
def llamacpp_logs(tail: int = 200) -> dict:
    return {"lines": get_manager().get_logs(tail=tail)}
