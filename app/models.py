from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ImageJobRequest(BaseModel):
    prompt: str
    width: int = 512
    height: int = 512
    steps: int = 20
    model: Optional[str] = None
    negative_prompt: Optional[str] = None


class VoiceJobRequest(BaseModel):
    text: str
    voice: str = "default"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    language: Optional[str] = None
    instruct: Optional[str] = None
    ref_text: Optional[str] = None
    num_step: Optional[int] = Field(default=None, ge=4, le=64)
    guidance_scale: Optional[float] = Field(default=None, ge=0.0, le=4.0)
    voice_preset_id: Optional[str] = None


class JobStatus(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class JobCreatedResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: datetime


class JobListResponse(BaseModel):
    jobs: list[JobStatus]
    total: int


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime


class ArtifactEntry(BaseModel):
    filename: str
    size: int
    created_at: datetime


class OmniVoiceStatusResponse(BaseModel):
    ephemeral_available: bool
    active_voice_jobs: int
    infer_base_command: list[str]
