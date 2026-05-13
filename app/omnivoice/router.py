from __future__ import annotations

from fastapi import APIRouter

from .config import OmniVoiceConfig, get_config, save_config
from .manager import get_manager

router = APIRouter(prefix="/v1/omnivoice", tags=["omnivoice"])


@router.get("/status")
async def get_omnivoice_status() -> dict:
    config = get_config()
    manager = get_manager()
    return {
        "ephemeral_available": manager.ephemeral_available(),
        "active_voice_jobs": manager.active_voice_jobs,
        "infer_base_command": config.infer_base_command or ["omnivoice-infer"],
    }


@router.get("/config", response_model=OmniVoiceConfig)
def get_omnivoice_config() -> OmniVoiceConfig:
    return get_config()


@router.put("/config", response_model=OmniVoiceConfig)
def update_omnivoice_config(new_config: OmniVoiceConfig) -> OmniVoiceConfig:
    save_config(new_config)
    return new_config
