from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class ImageJobRequest(BaseModel):
    prompt: str
    width: int = 512
    height: int = 512
    steps: int = 20
    model: Optional[str] = None
    negative_prompt: Optional[str] = None


class VoiceJobRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    speed: float = 1.0
    language: Optional[str] = None


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
