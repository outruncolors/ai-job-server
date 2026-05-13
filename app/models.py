from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class ImageJobRequest(BaseModel):
    workflow: str
    params: dict[str, Any] = {}


class VoiceSegment(BaseModel):
    text: str
    delay_ms: int = Field(default=500, ge=0, le=30_000)


class VoiceJobRequest(BaseModel):
    text: Optional[str] = None
    segments: Optional[list[VoiceSegment]] = None
    voice: str = "default"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    language: Optional[str] = None
    instruct: Optional[str] = None
    ref_text: Optional[str] = None
    num_step: Optional[int] = Field(default=None, ge=4, le=64)
    guidance_scale: Optional[float] = Field(default=None, ge=0.0, le=4.0)
    voice_preset_id: Optional[str] = None
    auto_segment: bool = False
    auto_segment_llm_base_url: Optional[str] = None
    auto_segment_llm_model: Optional[str] = None

    @model_validator(mode="after")
    def _require_text_or_segments(self) -> "VoiceJobRequest":
        if not self.text and not self.segments:
            raise ValueError("Either 'text' or 'segments' must be provided")
        return self


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


class ResourceStats(BaseModel):
    used: int
    total: int
    percent: float


class JobCounts(BaseModel):
    queued: int
    running: int
    done: int
    failed: int


class ServerStatsResponse(BaseModel):
    cpu_percent: float
    memory: ResourceStats
    disk: ResourceStats
    uptime_seconds: float
    jobs: JobCounts
    hostname: str
    python_version: str


class ServerRestartResponse(BaseModel):
    ok: bool
    message: str
