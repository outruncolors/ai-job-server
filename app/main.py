from __future__ import annotations

import shutil
import tempfile
import zipfile

import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .llm_config import (
    delete_preset as delete_llm_endpoint,
    get_default_as_chain_llm_config,
    list_presets as list_llm_endpoints,
    save_preset as save_llm_endpoint,
    set_default as set_llm_endpoint_default,
)
from .llm.models import LLMPreset
from . import llm_presets as _llm_presets
from .job_queue import get_job_queue, recover_interrupted_jobs
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
from .image_prompts import (
    create_prompt,
    delete_prompt,
    get_prompt,
    list_prompts,
    update_prompt,
)
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
from .llamacpp.manager import get_manager as get_llamacpp_manager
from .llamacpp.router import router as llamacpp_router
from .llamacpp.embed_manager import get_embed_manager
from .llamacpp.embed_router import router as llamacpp_embed_router
from .apps.blaboratory.router import router as blaboratory_router
from .apps.hoodat.router import router as hoodat_router
from .apps.prattletale.router import router as prattletale_router
from . import jobs as _jobs_module
from .jobs import (
    build_jobs_zip,
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
from .server import (
    find_peer_for_capability,
    get_git_sha,
    get_local_capabilities,
    get_peers,
    get_server_stats,
    requires_capability,
    schedule_restart,
)
from .peer_health import (
    get_peer_health_snapshot,
    start_peer_poller,
    stop_peer_poller,
)
from .deploy_secondary import get_runner as get_deploy_runner
from .omnivoice.config import get_config
from .omnivoice.manager import get_manager
from .omnivoice.router import router as omnivoice_router
from .voice_presets_router import router as presets_router
from .mcp.router import router as mcp_router
from .embed_lab.router import router as embed_lab_router
from .prompt_pal.router import router as prompt_pal_router
from .multimodal.router import router as multimodal_router
from .profiles import (
    apply_from_zip,
    delete_profile,
    export_to_zip,
    get_active,
    get_active_id,
    get_profile,
    import_as_new,
    list_profiles,
    overwrite_profile,
    save_profile,
    set_active,
)


def _build_recovery_runner(entry: dict):
    """Construct a zero-arg coroutine factory for a recovered queued job."""
    job_type = entry["job_type"]
    job_id = entry["job_id"]
    job_dir = entry["job_dir"]
    requested = (entry["request"] or {}).get("requested") or {}
    if job_type == "image":
        try:
            req = ImageJobRequest(**requested)
        except Exception:
            return None

        async def runner():
            await execute_image_job(
                job_id, job_dir, req, get_comfy_config(), get_comfy_manager()
            )

        return runner
    if job_type == "voice":
        try:
            req = VoiceJobRequest(**requested)
        except Exception:
            return None

        async def runner():
            await execute_voice_job(job_id, job_dir, req, get_config(), get_manager())

        return runner
    if job_type == "chain":
        try:
            req = ChainJobRequest(**requested)
        except Exception:
            return None

        async def runner():
            queue = get_job_queue()
            bus = queue.create_bus(job_id)
            try:
                await execute_chain_job(job_id, job_dir, req, event_bus=bus)
            finally:
                queue.close_bus(job_id)

        return runner
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_comfy_config()
    if cfg.autostart:
        try:
            await get_comfy_manager().start()
        except Exception as exc:
            print(f"ComfyUI autostart skipped: {exc}")
    if "llm" in get_local_capabilities():
        mgr = get_llamacpp_manager()
        try:
            adopted = await mgr.adopt()
            if not adopted:
                # No preset is loaded yet — the manager is instantiated and
                # ready for ensure-loaded calls; an explicit start with a
                # preset is required to spawn llama.cpp.
                pass
        except Exception as exc:
            print(f"llama.cpp adoption check skipped: {exc}")
        # Embed server (D1): adopt if already running, else start it (no-op when
        # embed_model_path is unset — start() raises and we just log + skip).
        embed_mgr = get_embed_manager()
        try:
            if not await embed_mgr.adopt():
                await embed_mgr.start()
        except Exception as exc:
            print(f"embed server start skipped: {exc}")
    # Seed any registered app prompts (Blaboratory, Hoodat, …) into the Prompt
    # Pal store so they are editable in the UI. Seed-if-absent — never clobbers
    # a user's edits. Best-effort: a bad prompt file must not block startup.
    try:
        from .prompt_pal.registry import seed_registered
        seed_registered()
    except Exception as exc:
        print(f"prompt-pal seeding skipped: {exc}")
    # Seed Prattletale's default message-style wildcard (seed-if-absent; the user
    # can retune the distribution in the Wildcards UI). Best-effort.
    try:
        from .apps.prattletale.seed import seed_message_style_wildcard
        seed_message_style_wildcard()
    except Exception as exc:
        print(f"prattletale wildcard seeding skipped: {exc}")
    # Import Prattletale plugin packages (so their register() runs) and seed each
    # plugin's Prompt Pal entries. Seed-if-absent, best-effort. Beside the Prompt
    # Pal + wildcard seeding above so a plugin's prompts are editable in the UI.
    try:
        from .apps.prattletale.plugins.registry import seed_plugins
        seed_plugins()
    except Exception as exc:
        print(f"prattletale plugin seeding skipped: {exc}")
    queue = get_job_queue()
    await queue.start()
    for entry in recover_interrupted_jobs(_jobs_module.JOBS_BASE):
        runner = _build_recovery_runner(entry)
        if runner is not None:
            await queue.enqueue(entry["job_id"], runner)
    await start_scheduler()
    await start_peer_poller()
    from .apps.blaboratory.sim_clock import (
        start_sim_clock_if_desired,
        stop_sim_clock,
    )
    await start_sim_clock_if_desired()
    yield
    if "llm" in get_local_capabilities():
        try:
            await get_embed_manager().stop()
        except Exception as exc:
            print(f"embed server stop skipped: {exc}")
    await stop_sim_clock(persist=False)
    await stop_peer_poller()
    await stop_scheduler()
    await queue.stop()


app = FastAPI(title="ai-job-server", version="0.1.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent.parent / "static"
DOCS_DIR = Path(__file__).parent.parent / "docs"

app.include_router(comfyui_router, dependencies=[Depends(requires_capability("image"))])
app.include_router(omnivoice_router, dependencies=[Depends(requires_capability("voice"))])
app.include_router(llamacpp_router, dependencies=[Depends(requires_capability("llm"))])
app.include_router(llamacpp_embed_router, dependencies=[Depends(requires_capability("llm"))])
app.include_router(presets_router)
app.include_router(mcp_router)
app.include_router(embed_lab_router)
app.include_router(blaboratory_router)
app.include_router(hoodat_router)
app.include_router(prattletale_router)
app.include_router(prompt_pal_router)
# Vision + Speech-to-Text. Not capability-gated: runs on the web node and routes
# to the llm node internally (see app/multimodal/router.py).
app.include_router(multimodal_router)

from app.cruddables.router import router as cruddables_router  # noqa: E402
from app.packs.router import router as packs_router  # noqa: E402
from app.sfx.router import router as sfx_router  # noqa: E402
from app.memory.routes import router as memory_router  # noqa: E402

app.include_router(cruddables_router)
app.include_router(packs_router)
# SFX is additive (like voice) — no capability gate.
app.include_router(sfx_router)
# Memory is app-agnostic + file-first — additive, not capability-gated.
app.include_router(memory_router)


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@app.post(
    "/v1/jobs/image",
    response_model=JobCreatedResponse,
    status_code=202,
    dependencies=[Depends(requires_capability("image"))],
)
async def create_image_job(req: ImageJobRequest):
    input_text = req.prompt
    data = create_job("image", req.model_dump(), input_text)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    async def runner():
        await execute_image_job(
            job_id, job_dir, req, get_comfy_config(), get_comfy_manager()
        )

    await get_job_queue().enqueue(job_id, runner)
    return JobCreatedResponse(**data)


@app.post(
    "/v1/jobs/voice",
    response_model=JobCreatedResponse,
    status_code=202,
    dependencies=[Depends(requires_capability("voice"))],
)
async def create_voice_job(req: VoiceJobRequest):
    input_text = req.text or (req.segments[0].text if req.segments else "")
    data = create_job("voice", req.model_dump(), input_text)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    async def runner():
        await execute_voice_job(job_id, job_dir, req, get_config(), get_manager())

    await get_job_queue().enqueue(job_id, runner)
    return JobCreatedResponse(**data)


@app.post("/v1/jobs/chain", response_model=JobCreatedResponse, status_code=202)
async def create_chain_job(req: ChainJobRequest):
    # Fill llm from the default endpoint preset (or the llm-peer fallback) when
    # the caller didn't supply one. Keeps single-machine and multi-machine users
    # from needing to configure an endpoint preset just to run chain jobs.
    if req.llm is None:
        try:
            req.llm = get_default_as_chain_llm_config()
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)
    patch_initial_chain_status(job_dir, len(req.steps))
    queue = get_job_queue()
    # Create the bus eagerly so an SSE client opening EventSource immediately
    # after the POST 202 returns sees the live bus rather than falling through
    # to the disk-snapshot path before the worker picks the job up.
    queue.create_bus(job_id)

    async def runner():
        bus = queue.get_bus(job_id)
        try:
            await execute_chain_job(job_id, job_dir, req, event_bus=bus)
        finally:
            queue.close_bus(job_id)

    await queue.enqueue(job_id, runner)
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


def _zip_response(job_ids: list[str], filename: str) -> FileResponse:
    tmp = tempfile.NamedTemporaryFile(prefix="jobs-", suffix=".zip", delete=False)
    tmp.close()
    out_path = Path(tmp.name)
    count = build_jobs_zip(job_ids, out_path)
    if count == 0:
        out_path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="No artifacts to download")
    return FileResponse(
        out_path,
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(lambda: out_path.unlink(missing_ok=True)),
    )


@app.post("/v1/jobs/download")
def download_selected_jobs(body: dict):
    ids = body.get("job_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="job_ids must be a non-empty list")
    fname = f"job-{ids[0][:8]}.zip" if len(ids) == 1 else f"jobs-{len(ids)}.zip"
    return _zip_response(ids, fname)


@app.get("/v1/jobs/download-all")
def download_all_jobs_zip():
    ids = [j["job_id"] for j in list_jobs()]
    if not ids:
        raise HTTPException(status_code=404, detail="No jobs")
    return _zip_response(ids, f"all-jobs-{len(ids)}.zip")


@app.get("/v1/jobs/{job_id}", response_model=JobStatus)
def get_job_detail(job_id: str):
    data = get_job(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**data)


@app.delete("/v1/jobs/{job_id}", status_code=200)
def delete_job(job_id: str):
    import json as _json

    job_dir = find_job_dir(job_id)
    if job_dir is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status_file = job_dir / "status.json"
    current_status: Optional[str] = None
    if status_file.exists():
        try:
            current_status = _json.loads(
                status_file.read_text(encoding="utf-8")
            ).get("status")
        except (OSError, _json.JSONDecodeError):
            current_status = None

    if current_status == "queued":
        get_job_queue().cancel_queued(job_id)
        data = _json.loads(status_file.read_text(encoding="utf-8"))
        data["status"] = "cancelled"
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        status_file.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        return {"cancelled": job_id}

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


@app.get("/v1/jobs/{job_id}/stream")
async def stream_chain_job(job_id: str, request: Request):
    """Server-Sent Events stream of chain job events.

    For a live job: subscribes to the in-memory EventBus, replaying history
    first then forwarding new events until ``job_done``. For a job whose bus
    has expired (or never existed): synthesizes events from disk artifacts.
    """
    from .chain.sse import event_stream_from_bus, event_stream_from_disk

    job_dir = find_job_dir(job_id)
    if job_dir is None:
        raise HTTPException(status_code=404, detail="Job not found")
    bus = get_job_queue().get_bus(job_id)
    if bus is not None:
        gen = event_stream_from_bus(bus, request)
    else:
        gen = event_stream_from_disk(job_id, job_dir)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/v1/chain-sequences")
def get_chain_sequences():
    return {"sequences": list_sequences()}


@app.post("/v1/chain-sequences", status_code=200)
async def upsert_chain_sequence(body: dict):
    try:
        return save_sequence(
            body["name"],
            body["steps"],
            variables=body.get("variables") or [],
        )
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


@app.get("/v1/profiles")
def list_profiles_route():
    return {"profiles": list_profiles(), "active_id": get_active_id()}


@app.get("/v1/profiles/active")
def get_active_profile_route():
    return {"active": get_active()}


@app.post("/v1/profiles", status_code=201)
async def create_profile_route(body: dict):
    try:
        return save_profile(
            name=body.get("name", ""),
            description=body.get("description", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/v1/profiles/import", status_code=201)
async def import_profile_route(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    mode: Optional[str] = Form(None),
):
    if mode is not None and mode not in ("replace", "merge"):
        raise HTTPException(status_code=422, detail="mode must be 'replace' or 'merge'")

    tmp_fd = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        shutil.copyfileobj(file.file, tmp_fd)
    finally:
        tmp_fd.close()
    zip_path = Path(tmp_fd.name)

    try:
        if mode is None:
            try:
                entry = import_as_new(zip_path, name=name)
            except (ValueError, zipfile.BadZipFile) as exc:
                raise HTTPException(status_code=422, detail=str(exc) or "malformed bundle")
            return entry
        try:
            report = apply_from_zip(zip_path, mode=mode)  # type: ignore[arg-type]
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(status_code=422, detail=str(exc) or "malformed bundle")
        return {
            "applied": True,
            "mode": report.mode,
            "domains": report.domains,
            "assets_copied": report.assets_copied,
            "asset_warnings": report.asset_warnings,
        }
    finally:
        zip_path.unlink(missing_ok=True)


@app.get("/v1/profiles/{pid}/export")
def export_profile_route(pid: str):
    entry = get_profile(pid)
    if entry is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    out_path = Path(tmp.name)
    export_to_zip(pid, out_path)
    safe_name = entry["name"].replace("/", "_").replace("\\", "_")
    return FileResponse(
        out_path,
        media_type="application/zip",
        filename=f"{safe_name}.zip",
        background=BackgroundTask(out_path.unlink, missing_ok=True),
    )


@app.post("/v1/profiles/{pid}/overwrite", status_code=200)
def overwrite_profile_route(pid: str):
    entry = overwrite_profile(pid)
    if entry is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return entry


@app.post("/v1/profiles/{pid}/activate", status_code=200)
def activate_profile_route(pid: str):
    try:
        report = set_active(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "active_id": pid,
        "domains": report.domains,
        "assets_copied": report.assets_copied,
        "asset_warnings": report.asset_warnings,
    }


@app.delete("/v1/profiles/{pid}", status_code=200)
def delete_profile_route(pid: str):
    if not delete_profile(pid):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"ok": True}


@app.get("/v1/image-prompts")
def get_image_prompts():
    return {"prompts": list_prompts()}


@app.post("/v1/image-prompts", status_code=201)
async def create_image_prompt(body: dict):
    try:
        return create_prompt(
            name=body.get("name", ""),
            prompt=body.get("prompt", ""),
            workflow=body.get("workflow"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/v1/image-prompts/{prompt_id}")
def get_image_prompt(prompt_id: str):
    p = get_prompt(prompt_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Image prompt not found")
    return p


@app.put("/v1/image-prompts/{prompt_id}", status_code=200)
async def update_image_prompt(prompt_id: str, body: dict):
    try:
        result = update_prompt(prompt_id, **body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Image prompt not found")
    return result


@app.delete("/v1/image-prompts/{prompt_id}", status_code=200)
def remove_image_prompt(prompt_id: str):
    if not delete_prompt(prompt_id):
        raise HTTPException(status_code=404, detail="Image prompt not found")
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
    try:
        return create_wildcard(
            name=body.get("name", ""),
            entries=body.get("entries", []),
            description=body.get("description", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.put("/v1/wildcards/{wid}", status_code=200)
async def update_wildcard_route(wid: str, body: dict):
    try:
        result = update_wildcard(
            wid,
            name=body.get("name", ""),
            entries=body.get("entries", []),
            description=body.get("description", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Wildcard not found")
    return result


@app.delete("/v1/wildcards/{wid}", status_code=200)
def remove_wildcard(wid: str):
    if not delete_wildcard(wid):
        raise HTTPException(status_code=404, detail="Wildcard not found")
    return {"ok": True}


# LLM endpoint presets — OpenAI-compatible HTTP API configs used by chain jobs.
# (Renamed from /v1/llm-presets so /v1/llm-presets can address llama.cpp model
# load presets per the multi-machine plan.)
@app.get("/v1/llm-endpoints")
def get_llm_endpoints():
    return list_llm_endpoints()


@app.post("/v1/llm-endpoints", status_code=200)
async def upsert_llm_endpoint(body: dict):
    try:
        return save_llm_endpoint(body).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/v1/llm-endpoints/{endpoint_id}", status_code=200)
def remove_llm_endpoint(endpoint_id: str):
    if not delete_llm_endpoint(endpoint_id):
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return {"ok": True}


@app.put("/v1/llm-endpoints/default", status_code=200)
async def set_llm_endpoint_default_route(body: dict):
    endpoint_id = body.get("id")
    if not set_llm_endpoint_default(endpoint_id):
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return {"ok": True}


# LLM model presets — llama.cpp load configs (model_path + args + capabilities).
# Resolved by /v1/llamacpp/ensure-loaded when called with {"preset": "name"}.
#
# Presets physically live on the node that runs llama-server (the "llm"-capable
# peer). Nodes without "llm" capability proxy these routes to that peer so the
# chain UI's preset dropdown + the Server > LLM > Models sub-tab work from any
# machine — otherwise the primary's UI would show an empty list because there
# is no llm-server on it to load anything.

async def _proxy_llm_presets(
    method: str,
    sub_path: str = "",
    *,
    json_body: Optional[dict] = None,
    success_status: int = 200,
):
    """Forward an /v1/llm-presets... request to the LLM-capable peer.

    Returns the peer's JSON body. Raises HTTPException for unreachable peer
    (503) or non-2xx peer responses (passes through status + body).
    """
    peer = find_peer_for_capability("llm")
    if peer is None:
        raise HTTPException(
            status_code=503,
            detail="No node with 'llm' capability available (neither local nor any configured peer)",
        )
    url = f"http://{peer.host}:{peer.port}/v1/llm-presets{sub_path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.request(method, url, json=json_body)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM peer at {peer.host}:{peer.port} unreachable: {exc}",
        ) from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HTTPException(status_code=r.status_code, detail=detail)
    return r.json()


@app.get("/v1/llm-presets")
async def get_llm_presets_route():
    if "llm" in get_local_capabilities():
        return {"presets": _llm_presets.list_presets()}
    return await _proxy_llm_presets("GET")


@app.get("/v1/llm-presets/{name}")
async def get_llm_preset_route(name: str):
    if "llm" in get_local_capabilities():
        data = _llm_presets.get_preset(name)
        if data is None:
            raise HTTPException(status_code=404, detail="LLM preset not found")
        return data
    return await _proxy_llm_presets("GET", f"/{name}")


@app.post("/v1/llm-presets", status_code=201)
async def create_llm_preset_route(body: dict):
    if "llm" in get_local_capabilities():
        try:
            preset = LLMPreset(**body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if _llm_presets.get_preset(preset.name) is not None:
            raise HTTPException(
                status_code=409, detail=f"LLM preset {preset.name!r} already exists"
            )
        return _llm_presets.save_preset(preset)
    return await _proxy_llm_presets("POST", json_body=body)


@app.put("/v1/llm-presets/{name}", status_code=200)
async def update_llm_preset_route(name: str, body: dict):
    if "llm" in get_local_capabilities():
        try:
            path_preset = LLMPreset(**{**body, "name": name})
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if _llm_presets.get_preset(name) is None:
            raise HTTPException(status_code=404, detail="LLM preset not found")
        return _llm_presets.save_preset(path_preset)
    return await _proxy_llm_presets("PUT", f"/{name}", json_body=body)


@app.delete("/v1/llm-presets/{name}", status_code=200)
async def delete_llm_preset_route(name: str):
    if "llm" in get_local_capabilities():
        if not _llm_presets.delete_preset(name):
            raise HTTPException(status_code=404, detail="LLM preset not found")
        return {"ok": True}
    return await _proxy_llm_presets("DELETE", f"/{name}")


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


@app.get("/v1/server/capabilities")
def server_capabilities():
    peers = get_peers()
    return {
        "local": sorted(get_local_capabilities()),
        "peers": [p.model_dump() for p in peers],
    }


@app.get("/v1/server/peers")
def server_peers():
    snap = get_peer_health_snapshot()
    return {
        "local_git_sha": get_git_sha(),
        "peers": [
            {**p.model_dump(), "health": snap.get(p.name)}
            for p in get_peers()
        ],
    }


@app.get("/v1/server/health")
def server_health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": get_git_sha(),
        "capabilities": sorted(get_local_capabilities()),
        "uptime_seconds": get_server_stats()["uptime_seconds"],
    }


@app.post("/v1/server/restart", response_model=ServerRestartResponse)
def server_restart(background_tasks: BackgroundTasks):
    background_tasks.add_task(schedule_restart)
    return ServerRestartResponse(ok=True, message="Restart scheduled")


@app.post("/v1/server/deploy-secondary")
async def server_deploy_secondary(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    peer_host = (body or {}).get("peer_host") if isinstance(body, dict) else None

    runner = get_deploy_runner()
    try:
        snap = runner.start_secondary(peer_host=peer_host)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return snap


@app.post("/v1/server/deploy-all")
async def server_deploy_all(request: Request):
    """Catch-Up: commit + merge to master + push local/gh + deploy-secondary."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    message = (body.get("message") or "").strip()
    peer_host = body.get("peer_host")
    if not message:
        raise HTTPException(status_code=400, detail="a commit message is required")

    runner = get_deploy_runner()
    try:
        snap = runner.start_all(message=message, peer_host=peer_host)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return snap


@app.get("/v1/server/deploy-status")
def server_deploy_status():
    """Shared status poll for whichever deploy script is/was running."""
    return get_deploy_runner().snapshot()


@app.get("/v1/server/deploy-secondary")
def server_deploy_secondary_status():
    # Back-compat alias for /v1/server/deploy-status.
    return get_deploy_runner().snapshot()


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
