from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .jobs import (
    clear_pending_jobs,
    create_job,
    execute_voice_job,
    find_job_dir,
    get_job,
    get_job_file,
    list_jobs,
)
from .models import (
    HealthResponse,
    ImageJobRequest,
    JobCreatedResponse,
    JobListResponse,
    JobStatus,
    VoiceJobRequest,
)
from .omnivoice.config import get_config
from .omnivoice.manager import get_manager
from .omnivoice.router import router as omnivoice_router

app = FastAPI(title="ai-job-server", version="0.1.0")

STATIC_DIR = Path(__file__).parent.parent / "static"

app.include_router(omnivoice_router)


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@app.post("/v1/jobs/image", response_model=JobCreatedResponse, status_code=202)
def create_image_job(req: ImageJobRequest):
    input_text = req.prompt
    data = create_job("image", req.model_dump(), input_text)
    return JobCreatedResponse(**data)


@app.post("/v1/jobs/voice", response_model=JobCreatedResponse, status_code=202)
def create_voice_job(req: VoiceJobRequest, background_tasks: BackgroundTasks):
    data = create_job("voice", req.model_dump(), req.text)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)
    background_tasks.add_task(
        execute_voice_job,
        job_id,
        job_dir,
        req,
        get_config(),
        get_manager(),
    )
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
