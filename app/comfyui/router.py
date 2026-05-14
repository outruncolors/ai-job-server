from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .config import ComfyUIConfig, get_config, save_config
from .manager import get_manager
from .workflows import list_workflows

router = APIRouter(prefix="/v1/comfyui", tags=["comfyui"])


@router.get("/status")
async def get_comfyui_status() -> dict:
    return await get_manager().status()


@router.post("/start")
async def start_comfyui() -> dict:
    try:
        return await get_manager().start()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/stop")
async def stop_comfyui() -> dict:
    return await get_manager().stop()


@router.post("/restart")
async def restart_comfyui() -> dict:
    try:
        return await get_manager().restart()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/config", response_model=ComfyUIConfig)
def get_comfyui_config() -> ComfyUIConfig:
    return get_config()


@router.put("/config", response_model=ComfyUIConfig)
def update_comfyui_config(new_config: ComfyUIConfig) -> ComfyUIConfig:
    save_config(new_config)
    return new_config


@router.get("/workflows")
def get_workflows() -> dict:
    return {"workflows": list_workflows()}


@router.get("/system_stats")
async def comfyui_system_stats() -> dict:
    """Pass-through of ComfyUI /system_stats for GPU display."""
    from .client import ComfyUIClient
    cfg = get_config()
    client = ComfyUIClient(f"http://{cfg.host}:{cfg.port}")
    try:
        return await client.system_stats()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ComfyUI unavailable: {exc}")
