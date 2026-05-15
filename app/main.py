from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .llm_config import delete_preset, list_presets, save_preset, set_default
from .ticks.persistence import delete_tick, get_tick, list_ticks, save_tick, update_tick_fields
from .ticks.scheduler import get_scheduler, start_scheduler, stop_scheduler
from .chain.context_library import (
    create_item,
    delete_item,
    get_item,
    list_items,
    update_item,
)
from .chain.executor import execute_chain_job, list_chain_steps, patch_initial_chain_status
from .chain.models import ChainJobRequest
from .chain.sequences import delete_sequence, duplicate_sequence, list_sequences, save_sequence
from .tickets.store import (
    create_ticket,
    delete_ticket,
    get_ticket,
    list_tickets,
    next_ticket,
    reorder_tickets,
    update_ticket,
)
from .wildcards import create_wildcard, delete_wildcard, list_wildcards, update_wildcard
from .comfyui.config import get_config as get_comfy_config
from .comfyui.manager import get_manager as get_comfy_manager
from .comfyui.router import router as comfyui_router
from .comfyui.runner import execute_image_job
from .jobs import (
    clear_all_jobs,
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
    ServerRestartResponse,
    ServerStatsResponse,
    VoiceJobRequest,
)
from .server import get_server_stats, schedule_restart
from .omnivoice.config import get_config
from .omnivoice.manager import get_manager
from .omnivoice.router import router as omnivoice_router
from .voice_presets_router import router as presets_router
from .mcp.router import router as mcp_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_comfy_config()
    if cfg.autostart:
        try:
            await get_comfy_manager().start()
        except Exception as exc:
            print(f"ComfyUI autostart skipped: {exc}")
    await start_scheduler()
    yield
    await stop_scheduler()


app = FastAPI(title="ai-job-server", version="0.1.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent.parent / "static"
DOCS_DIR = Path(__file__).parent.parent / "docs"

app.include_router(comfyui_router)
app.include_router(omnivoice_router)
app.include_router(presets_router)
app.include_router(mcp_router)


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@app.post("/v1/jobs/image", response_model=JobCreatedResponse, status_code=202)
def create_image_job(req: ImageJobRequest, background_tasks: BackgroundTasks):
    input_text = req.prompt
    data = create_job("image", req.model_dump(), input_text)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)
    background_tasks.add_task(
        execute_image_job,
        job_id,
        job_dir,
        req,
        get_comfy_config(),
        get_comfy_manager(),
    )
    return JobCreatedResponse(**data)


@app.post("/v1/jobs/voice", response_model=JobCreatedResponse, status_code=202)
def create_voice_job(req: VoiceJobRequest, background_tasks: BackgroundTasks):
    input_text = req.text or (req.segments[0].text if req.segments else "")
    data = create_job("voice", req.model_dump(), input_text)
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


@app.delete("/v1/jobs/all", status_code=200)
def clear_all():
    removed = clear_all_jobs()
    return {"removed": removed}


@app.get("/v1/jobs/{job_id}", response_model=JobStatus)
def get_job_detail(job_id: str):
    data = get_job(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**data)


@app.delete("/v1/jobs/{job_id}", status_code=200)
def delete_job(job_id: str):
    job_dir = find_job_dir(job_id)
    if job_dir is None:
        raise HTTPException(status_code=404, detail="Job not found")
    shutil.rmtree(job_dir)
    return {"deleted": job_id}


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
    try:
        return save_sequence(body["name"], body["steps"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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


@app.get("/v1/tickets")
def get_tickets():
    return {"tickets": list_tickets()}


@app.get("/v1/tickets/next")
def get_next_ticket():
    t = next_ticket()
    if t is None:
        raise HTTPException(status_code=404, detail="No todo tickets")
    return t


@app.post("/v1/tickets", status_code=201)
async def create_ticket_route(body: dict):
    try:
        return create_ticket(
            title=body.get("title", ""),
            description=body.get("description", ""),
            file_hints=body.get("file_hints") or [],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/v1/tickets/reorder", status_code=200)
async def reorder_tickets_route(body: dict):
    ids = body.get("ids")
    if not isinstance(ids, list):
        raise HTTPException(status_code=422, detail="ids must be a list")
    try:
        return {"tickets": reorder_tickets(ids)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/v1/tickets/{tid}")
def get_ticket_route(tid: str):
    t = get_ticket(tid)
    if t is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@app.patch("/v1/tickets/{tid}", status_code=200)
async def update_ticket_route(tid: str, body: dict):
    try:
        result = update_ticket(tid, **body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return result


@app.delete("/v1/tickets/{tid}", status_code=200)
def delete_ticket_route(tid: str):
    if not delete_ticket(tid):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {"ok": True}


@app.get("/v1/context-items")
def get_context_items():
    return {"items": list_items()}


@app.post("/v1/context-items", status_code=201)
async def create_context_item(body: dict):
    return create_item(
        title=body.get("title", ""),
        tags=body.get("tags", []),
        description=body.get("description", ""),
        content=body.get("content", ""),
    )


@app.get("/v1/context-items/{item_id}")
def get_context_item(item_id: str):
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Context item not found")
    return item


@app.put("/v1/context-items/{item_id}", status_code=200)
async def update_context_item(item_id: str, body: dict):
    result = update_item(item_id, **{k: v for k, v in body.items()})
    if result is None:
        raise HTTPException(status_code=404, detail="Context item not found")
    return result


@app.delete("/v1/context-items/{item_id}", status_code=200)
def remove_context_item(item_id: str):
    if not delete_item(item_id):
        raise HTTPException(status_code=404, detail="Context item not found")
    return {"ok": True}


@app.get("/v1/wildcards")
def get_wildcards():
    return {"wildcards": list_wildcards()}


@app.post("/v1/wildcards", status_code=201)
async def create_wildcard_route(body: dict):
    return create_wildcard(
        name=body.get("name", ""),
        entries=body.get("entries", []),
    )


@app.put("/v1/wildcards/{wid}", status_code=200)
async def update_wildcard_route(wid: str, body: dict):
    result = update_wildcard(wid, name=body.get("name", ""), entries=body.get("entries", []))
    if result is None:
        raise HTTPException(status_code=404, detail="Wildcard not found")
    return result


@app.delete("/v1/wildcards/{wid}", status_code=200)
def remove_wildcard(wid: str):
    if not delete_wildcard(wid):
        raise HTTPException(status_code=404, detail="Wildcard not found")
    return {"ok": True}


@app.get("/v1/llm-presets")
def get_llm_presets():
    return list_presets()


@app.post("/v1/llm-presets", status_code=200)
async def upsert_llm_preset(body: dict):
    try:
        return save_preset(body).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/v1/llm-presets/{preset_id}", status_code=200)
def remove_llm_preset(preset_id: str):
    if not delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}


@app.put("/v1/llm-presets/default", status_code=200)
async def set_llm_default(body: dict):
    preset_id = body.get("id")
    if not set_default(preset_id):
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}


@app.get("/v1/ticks")
def get_ticks():
    return {"ticks": list_ticks()}


@app.post("/v1/ticks", status_code=200)
async def upsert_tick(body: dict):
    try:
        return save_tick(body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/v1/ticks/{tick_id}", status_code=200)
def remove_tick(tick_id: str):
    if not delete_tick(tick_id):
        raise HTTPException(status_code=404, detail="Tick not found")
    return {"ok": True}


@app.post("/v1/ticks/{tick_id}/enable", status_code=200)
async def set_tick_enabled(tick_id: str, body: dict):
    result = update_tick_fields(tick_id, enabled=bool(body.get("enabled", True)))
    if result is None:
        raise HTTPException(status_code=404, detail="Tick not found")
    return result


@app.post("/v1/ticks/{tick_id}/fire", status_code=200)
async def fire_tick_now(tick_id: str, force: bool = False):
    tick = get_tick(tick_id)
    if tick is None:
        raise HTTPException(status_code=404, detail="Tick not found")
    job_id = await get_scheduler().fire_tick(tick_id, force=force)
    if job_id is None:
        tick = get_tick(tick_id)
        reason = tick.get("last_skip_reason", "unknown") if tick else "unknown"
        return {"fired": False, "skip_reason": reason}
    return {"fired": True, "job_id": job_id}


@app.get("/v1/ticks/{tick_id}/recent-jobs")
def get_tick_recent_jobs(tick_id: str, limit: int = 10):
    jobs = [
        j for j in list_jobs()
        if _job_fired_by_tick(j, tick_id)
    ]
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:limit]}


def _job_fired_by_tick(job_status: dict, tick_id: str) -> bool:
    job_dir = find_job_dir(job_status["job_id"])
    if job_dir is None:
        return False
    req_file = job_dir / "request.json"
    if not req_file.exists():
        return False
    try:
        data = __import__("json").loads(req_file.read_text(encoding="utf-8"))
        return data.get("fired_by_tick") == tick_id
    except Exception:
        return False


@app.post("/v1/ticks/preview", status_code=200)
async def preview_cron(body: dict):
    from croniter import croniter
    cron_expr = body.get("cron", "")
    try:
        it = croniter(cron_expr, datetime.now(timezone.utc))
        nexts = [it.get_next(datetime).replace(tzinfo=timezone.utc).isoformat() for _ in range(3)]
        return {"next": nexts}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/v1/server/stats", response_model=ServerStatsResponse)
def server_stats():
    return get_server_stats()


@app.post("/v1/server/restart", response_model=ServerRestartResponse)
def server_restart(background_tasks: BackgroundTasks):
    background_tasks.add_task(schedule_restart)
    return ServerRestartResponse(ok=True, message="Restart scheduled")


def _doc_title(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as fh:
            head = fh.read(512)
        for line in head.splitlines():
            s = line.strip()
            if s.startswith("# "):
                return s[2:].strip()
    except OSError:
        pass
    return path.stem.replace("-", " ").replace("_", " ").title()


def _dir_title(path: Path) -> str:
    return path.name.replace("-", " ").replace("_", " ").title()


def _build_doc_tree(directory: Path, rel_prefix: str = "") -> list[dict]:
    nodes: list[dict] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return nodes

    subdirs = sorted([p for p in entries if p.is_dir() and not p.name.startswith(".")],
                     key=lambda p: p.name.lower())
    files = sorted([p for p in entries if p.is_file() and p.suffix == ".md"],
                   key=lambda p: (p.name.lower() != "index.md", p.name.lower()))

    for d in subdirs:
        child_prefix = f"{rel_prefix}{d.name}/"
        nodes.append({
            "type": "dir",
            "path": child_prefix.rstrip("/"),
            "title": _dir_title(d),
            "children": _build_doc_tree(d, child_prefix),
        })

    for f in files:
        nodes.append({
            "type": "doc",
            "path": f"{rel_prefix}{f.name}",
            "title": _doc_title(f),
            "size": f.stat().st_size,
        })

    return nodes


@app.get("/v1/docs")
def list_docs():
    if not DOCS_DIR.exists():
        return {"tree": []}
    return {"tree": _build_doc_tree(DOCS_DIR)}


@app.get("/v1/docs/{doc_path:path}")
def get_doc(doc_path: str):
    if not doc_path.endswith(".md") or ".." in doc_path.split("/"):
        raise HTTPException(status_code=400, detail="Invalid doc path")
    try:
        resolved = (DOCS_DIR / doc_path).resolve()
        docs_root = DOCS_DIR.resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid doc path")
    if not resolved.is_relative_to(docs_root):
        raise HTTPException(status_code=400, detail="Invalid doc path")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Doc not found")
    return PlainTextResponse(resolved.read_text(encoding="utf-8"))


# Serve static UI from /
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
