from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

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
    mode: Optional[Literal["persistent", "ephemeral"]] = None
    instruct: Optional[str] = None
    ref_text: Optional[str] = None
    num_step: Optional[int] = Field(default=None, ge=4, le=64)
    guidance_scale: Optional[float] = Field(default=None, ge=0.0, le=4.0)


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


class OmniVoicePersistentStatus(BaseModel):
    desired_state: str
    process_state: str
    pid: Optional[int] = None
    api_base: str
    health: str
    last_error: Optional[str] = None


class OmniVoiceEphemeralStatus(BaseModel):
    available: Optional[bool] = None
    last_check: Optional[str] = None


class OmniVoiceStatusResponse(BaseModel):
    mode: str
    configured: bool
    persistent: OmniVoicePersistentStatus
    ephemeral: OmniVoiceEphemeralStatus
    active_voice_jobs: int
    updated_at: str
