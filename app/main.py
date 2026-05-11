from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .chain.executor import execute_chain_job, list_chain_steps, patch_initial_chain_status
from .chain.models import ChainJobRequest
from .chain.sequences import delete_sequence, duplicate_sequence, list_sequences, save_sequence
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
from .voice_presets_router import router as presets_router

app = FastAPI(title="ai-job-server", version="0.1.0")

STATIC_DIR = Path(__file__).parent.parent / "static"

app.include_router(omnivoice_router)
app.include_router(presets_router)


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


@app.post("/v1/jobs/chain", response_model=JobCreatedResponse, status_code=202)
async def create_chain_job(req: ChainJobRequest, background_tasks: BackgroundTasks):
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)
    patch_initial_chain_status(job_dir, len(req.steps))
    background_tasks.add_task(execute_chain_job, job_id, job_dir, req)
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


@app.get("/v1/jobs/{job_id}/steps")
def get_job_steps(job_id: str):
    job_dir = find_job_dir(job_id)
    if job_dir is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"steps": list_chain_steps(job_dir)}


@app.get("/v1/jobs/{job_id}/files/{filename:path}")
def get_job_file_endpoint(job_id: str, filename: str):
    path = get_job_file(job_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.get("/v1/chain-sequences")
def get_chain_sequences():
    return {"sequences": list_sequences()}


@app.post("/v1/chain-sequences", status_code=200)
async def upsert_chain_sequence(body: dict):
    return save_sequence(body["name"], body["steps"])


@app.delete("/v1/chain-sequences/{seq_id}", status_code=200)
def remove_chain_sequence(seq_id: str):
    if not delete_sequence(seq_id):
        raise HTTPException(status_code=404, detail="Sequence not found")
    return {"ok": True}


@app.post("/v1/chain-sequences/{seq_id}/duplicate", status_code=200)
def dup_chain_sequence(seq_id: str):
    result = duplicate_sequence(seq_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return result


# Serve static UI from /
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
