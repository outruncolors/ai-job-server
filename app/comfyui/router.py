from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from .config import ComfyUIConfig, get_config, save_config
from .downloader import DownloadError, get_downloader
from .manager import get_manager
from .workflows import list_workflows

_ALLOWED_UPLOAD_TYPES = {"image/png", "image/jpeg", "image/webp"}

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


@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...)) -> dict:
    """Proxy a single image upload to ComfyUI's /upload/image.

    Returns the stored filename so callers can reference it as a LoadImage input.
    """
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported content_type: {content_type or 'unknown'}",
        )

    from .client import ComfyUIClient
    cfg = get_config()
    client = ComfyUIClient(f"http://{cfg.host}:{cfg.port}")

    suffix = Path(file.filename or "upload").suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            data = await file.read()
            tmp.write(data)
            tmp.flush()
            try:
                resp = await client.upload_image(
                    tmp_path,
                    content_type=content_type,
                    filename=file.filename or tmp_path.name,
                )
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=503, detail=f"ComfyUI unavailable: {exc}"
                )
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    name = resp.get("name") or ""
    subfolder = resp.get("subfolder") or ""
    image = f"{subfolder}/{name}" if subfolder else name
    return {
        "image": image,
        "filename": name,
        "subfolder": subfolder,
        "type": resp.get("type", "input"),
    }


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


# ── Model downloader ────────────────────────────────────────────────────────


class DownloadRequest(BaseModel):
    url: str
    path: str
    overwrite: bool = False
    authorization: str | None = None


@router.post("/downloads")
async def start_model_download(body: DownloadRequest) -> dict:
    try:
        state = get_downloader().start(
            body.url, body.path, body.overwrite, body.authorization
        )
    except DownloadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {"id": state.id, "path": state.path}


@router.get("/downloads")
async def list_model_downloads() -> dict:
    return {"items": [s.to_public() for s in get_downloader().list_all()]}


@router.get("/downloads/{download_id}")
async def get_model_download(download_id: str) -> dict:
    state = get_downloader().get(download_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown download id")
    return state.to_public()


@router.post("/downloads/{download_id}/cancel")
async def cancel_model_download(download_id: str) -> Response:
    state = get_downloader().get(download_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown download id")
    if state.status != "running":
        raise HTTPException(status_code=409, detail=f"not running (status={state.status})")
    await get_downloader().cancel(download_id)
    return Response(status_code=204)
