"""REST API for the memory subsystem (``/v1/memory/*``).

Fail-soft: when memory is disabled, health/search say so rather than erroring. The
``/test/*`` routes only ever touch the ``test/memory_demo`` scope (there is no global dev
flag in this repo, so the scope restriction is the safety boundary).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .service import DEMO_SCOPE, get_service
from .models import (
    MemoryHealth,
    MemoryIndexResult,
    MemoryReindexRequest,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryUpdateRequest,
    MemoryWriteRequest,
)
from .models import ScopeType  # re-exported Literal for the /scopes endpoint
from typing import get_args

from . import store

router = APIRouter(prefix="/v1/memory", tags=["memory"])


@router.get("/health", response_model=MemoryHealth)
async def memory_health() -> MemoryHealth:
    return await get_service().health()


@router.get("/scopes")
async def memory_scopes() -> dict:
    return {
        "scope_types": list(get_args(ScopeType)),
        "scopes": store.list_scopes(),
    }


@router.get("/list")
async def memory_list(
    scope_type: str | None = None,
    scope_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Paginated metadata listing for the Memory Lab table (bodies excluded — the
    table shows metadata; the detail pane reads the body via ``/read/{id}``).

    Optional ``scope_type`` / ``scope_id`` narrow the listing. Newest-updated first.
    """
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    records = [r for r, _ in store.list_records()]
    if scope_type:
        records = [r for r in records if r.scope_type == scope_type]
    if scope_id:
        records = [r for r in records if r.scope_id == scope_id]
    records.sort(key=lambda r: (r.updated_at or r.created_at or ""), reverse=True)
    total = len(records)
    page = records[offset:offset + limit]
    items = [
        {
            "id": r.id,
            "title": r.title,
            "scope_type": r.scope_type,
            "scope_id": r.scope_id,
            "tags": list(r.tags or []),
            "source_type": r.source_type,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in page
    ]
    return {"ok": True, "items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/write")
async def memory_write(req: MemoryWriteRequest) -> dict:
    record, path = await get_service().write(req)
    return {"ok": True, "memory_id": record.id, "path": str(path)}


@router.post("/search", response_model=MemorySearchResponse)
async def memory_search(req: MemorySearchRequest) -> MemorySearchResponse:
    return await get_service().search(req)


@router.get("/read/{memory_id}")
async def memory_read(memory_id: str) -> dict:
    try:
        record = get_service().read(memory_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if record is None:
        raise HTTPException(status_code=404, detail=f"memory not found: {memory_id}")
    return {
        "ok": True,
        "memory": {
            "id": record.id,
            "title": record.title,
            "body": record.body,
            "metadata": record.frontmatter(),
        },
    }


@router.post("/update/{memory_id}")
async def memory_update(memory_id: str, req: MemoryUpdateRequest) -> dict:
    try:
        record = await get_service().update(memory_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if record is None:
        raise HTTPException(status_code=404, detail=f"memory not found: {memory_id}")
    return {"ok": True, "memory_id": record.id}


@router.post("/delete/{memory_id}")
async def memory_delete(memory_id: str) -> dict:
    try:
        record = await get_service().delete(memory_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if record is None:
        raise HTTPException(status_code=404, detail=f"memory not found: {memory_id}")
    return {"ok": True, "memory_id": record.id, "status": record.status}


@router.post("/reindex", response_model=MemoryIndexResult)
async def memory_reindex(req: MemoryReindexRequest) -> MemoryIndexResult:
    return await get_service().reindex(req)


# ── dev/test helpers — confined to the test/memory_demo scope ────────────────


@router.post("/test/seed-demo")
async def memory_seed_demo() -> dict:
    svc = get_service()
    records = await svc.create_demo_memories()
    return {
        "ok": True,
        "scope": DEMO_SCOPE.model_dump(),
        "memories": [{"memory_id": r.id, "title": r.title} for r in records],
    }


@router.post("/test/run-demo-searches")
async def memory_run_demo_searches() -> dict:
    return {"ok": True, "searches": await get_service().run_demo_searches()}


@router.post("/test/reset")
async def memory_reset_demo() -> dict:
    removed = get_service().reset_demo()
    return {"ok": True, "scope": DEMO_SCOPE.model_dump(), "removed": removed}
