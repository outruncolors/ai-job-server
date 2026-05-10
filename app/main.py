from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .jobs import clear_pending_jobs, create_job, get_job, get_job_file, list_jobs
from .models import (
    HealthResponse,
    ImageJobRequest,
    JobCreatedResponse,
    JobListResponse,
    JobStatus,
    VoiceJobRequest,
)

app = FastAPI(title="ai-job-server", version="0.1.0")

STATIC_DIR = Path(__file__).parent.parent / "static"


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@app.post("/v1/jobs/image", response_model=JobCreatedResponse, status_code=202)
def create_image_job(req: ImageJobRequest):
    input_text = req.prompt
    data = create_job("image", req.model_dump(), input_text)
    return JobCreatedResponse(**data)


@app.post("/v1/jobs/voice", response_model=JobCreatedResponse, status_code=202)
def create_voice_job(req: VoiceJobRequest):
    input_text = req.text
    data = create_job("voice", req.model_dump(), input_text)
    return JobCreatedResponse(**data)


@app.get("/v1/jobs", response_model=JobListResponse)
def get_jobs():
    jobs = list_jobs()
    return JobListResponse(jobs=[JobStatus(**j) for j in jobs], total=len(jobs))


@app.delete("/v1/jobs", status_code=200)
def clear_queue():
    removed = clear_pending_jobs()
    return {"removed": removed}


@app.get("/v1/jobs/{job_id}", response_model=JobStatus)
def get_job_detail(job_id: str):
    data = get_job(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**data)


@app.get("/v1/jobs/{job_id}/files/{filename}")
def get_job_file_endpoint(job_id: str, filename: str):
    path = get_job_file(job_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


# Serve static UI from /
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
