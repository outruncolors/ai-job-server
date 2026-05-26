"""Control routes for the app-managed embed ``llama-server`` (D1.2a).

Mirrors ``llamacpp/router.py`` but for the embed sibling: no preset resolution
(the embed server has a fixed model from config), just lifecycle + logs. Gated
behind the ``llm`` capability in ``app/main.py`` like the chat routes.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .embed_manager import get_embed_manager
from .manager import LlamaCppLoadError

router = APIRouter(prefix="/v1/llamacpp-embed", tags=["llamacpp-embed"])


@router.get("/status")
async def embed_status() -> dict:
    return await get_embed_manager().status()


@router.post("/start")
async def embed_start() -> dict:
    try:
        return await get_embed_manager().start()
    except LlamaCppLoadError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/stop")
async def embed_stop() -> dict:
    return await get_embed_manager().stop()


@router.post("/restart")
async def embed_restart() -> dict:
    try:
        return await get_embed_manager().restart()
    except LlamaCppLoadError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/logs")
def embed_logs(tail: int = 200) -> dict:
    return {"lines": get_embed_manager().get_logs(tail=tail)}
