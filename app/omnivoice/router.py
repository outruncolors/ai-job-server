from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..models import (
    OmniVoiceEphemeralStatus,
    OmniVoicePersistentStatus,
    OmniVoiceStatusResponse,
)
from .config import OmniVoiceConfig, get_config, save_config
from .manager import get_manager

router = APIRouter(prefix="/v1/omnivoice", tags=["omnivoice"])


def _build_status(config: OmniVoiceConfig) -> OmniVoiceStatusResponse:
    manager = get_manager()
    return OmniVoiceStatusResponse(
        mode=config.mode,
        configured=True,
        persistent=OmniVoicePersistentStatus(
            desired_state=manager.desired_state,
            process_state=manager.process_state,
            pid=manager.pid,
            api_base=config.persistent_api_base,
            health="unknown",
            last_error=manager.last_error,
        ),
        ephemeral=OmniVoiceEphemeralStatus(
            available=manager.ephemeral_available() if config.mode == "ephemeral" else None,
            last_check=datetime.now(timezone.utc).isoformat(),
        ),
        active_voice_jobs=manager.active_voice_jobs,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/status", response_model=OmniVoiceStatusResponse)
async def get_omnivoice_status() -> OmniVoiceStatusResponse:
    config = get_config()
    manager = get_manager()
    health = await manager.health_check(config)
    status = _build_status(config)
    status.persistent.health = health
    return status


@router.post("/start", response_model=OmniVoiceStatusResponse)
async def start_omnivoice() -> OmniVoiceStatusResponse:
    config = get_config()
    manager = get_manager()
    if not config.server_command:
        raise HTTPException(
            status_code=400,
            detail=(
                "server_command is not configured. "
                "Set it via PUT /v1/omnivoice/config before starting."
            ),
        )
    try:
        manager.start(config)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    health = await manager.health_check(config)
    status = _build_status(config)
    status.persistent.health = health
    return status


@router.post("/stop", response_model=OmniVoiceStatusResponse)
async def stop_omnivoice() -> OmniVoiceStatusResponse:
    config = get_config()
    get_manager().stop()
    status = _build_status(config)
    return status


@router.post("/restart", response_model=OmniVoiceStatusResponse)
async def restart_omnivoice() -> OmniVoiceStatusResponse:
    config = get_config()
    manager = get_manager()
    if not config.server_command:
        raise HTTPException(
            status_code=400,
            detail=(
                "server_command is not configured. "
                "Set it via PUT /v1/omnivoice/config before restarting."
            ),
        )
    try:
        manager.restart(config)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    health = await manager.health_check(config)
    status = _build_status(config)
    status.persistent.health = health
    return status


@router.get("/config", response_model=OmniVoiceConfig)
def get_omnivoice_config() -> OmniVoiceConfig:
    return get_config()


@router.put("/config", response_model=OmniVoiceConfig)
def update_omnivoice_config(new_config: OmniVoiceConfig) -> OmniVoiceConfig:
    old_config = get_config()
    save_config(new_config)
    if old_config.mode == "persistent" and new_config.mode == "ephemeral":
        get_manager().stop()
    return new_config
