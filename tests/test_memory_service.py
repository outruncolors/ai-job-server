from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.memory.models import (
    MemoryScope,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryUpdateRequest,
    MemoryWriteRequest,
)
from app.memory.service import DEMO_SCOPE, get_service

SCOPE = MemoryScope(scope_type="project", scope_id="ai-job-server")


def _write_req(title, body, tags=None):
    return MemoryWriteRequest(title=title, body=body, scope=SCOPE, tags=tags or [])


async def test_write_then_read():
    svc = get_service()
    rec, path = await svc.write(_write_req("Atomic UI", "prefers atomic tests"))
    back = svc.read(rec.id)
    assert back is not None and back.title == "Atomic UI"
    assert path.exists()


async def test_write_then_search():
    svc = get_service()
    await svc.write(_write_req("Lighthouse", "north of the harbor"))
    resp = await svc.search(MemorySearchRequest(query="lighthouse", scopes=[SCOPE]))
    assert resp.count == 1
    assert resp.backend == "plain"


async def test_update_then_search():
    svc = get_service()
    rec, _ = await svc.write(_write_req("Old", "nothing relevant here"))
    await svc.update(rec.id, MemoryUpdateRequest(body="now mentions bicycles"))
    resp = await svc.search(MemorySearchRequest(query="bicycles", scopes=[SCOPE]))
    assert resp.count == 1 and resp.results[0].memory_id == rec.id


async def test_delete_then_search():
    svc = get_service()
    rec, _ = await svc.write(_write_req("Lighthouse", "the lighthouse"))
    await svc.delete(rec.id)
    resp = await svc.search(MemorySearchRequest(query="lighthouse", scopes=[SCOPE]))
    assert resp.count == 0


async def test_reindex_plain_is_safe():
    svc = get_service()
    await svc.write(_write_req("x", "y"))
    from app.memory.models import MemoryReindexRequest

    res = await svc.reindex(MemoryReindexRequest(scopes=[SCOPE]))
    assert res.ok and res.backend == "plain"


async def test_missing_id_returns_none():
    svc = get_service()
    assert svc.read("mem_does_not_exist") is None


def test_invalid_scope_is_rejected():
    with pytest.raises(ValidationError):
        MemoryScope(scope_type="not_a_real_scope", scope_id="x")


def test_format_memory_block_caps_and_deterministic():
    svc = get_service()
    results = [
        MemorySearchResult(
            memory_id="m1",
            title="Title one",
            score=0.9,
            path="/x",
            snippet="body one",
            metadata={"scope_type": "project", "scope_id": "ai-job-server"},
        ),
        MemorySearchResult(
            memory_id="m2",
            title="Title two",
            score=0.5,
            path="/y",
            snippet="body two",
            metadata={"scope_type": "app", "scope_id": "hoodat"},
        ),
    ]
    block = svc.format_memory_block(results)
    assert "Relevant memories:" in block
    assert "1. Title one" in block and "2. Title two" in block
    assert "project/ai-job-server" in block
    # idempotent / deterministic
    assert svc.format_memory_block(results) == block
    # cap respected
    capped = svc.format_memory_block(results, max_chars=40)
    assert len(capped) <= 40
    assert svc.format_memory_block([]) == ""


async def test_demo_fixtures_confined_to_test_scope():
    svc = get_service()
    # seed a real memory in another scope that must survive a demo reset
    real, _ = await svc.write(_write_req("Real", "keep me"))
    await svc.create_demo_memories()
    searches = await svc.run_demo_searches()
    assert all(s["ok"] for s in searches), searches
    removed = svc.reset_demo()
    assert removed == 4
    # demo gone, real survives
    assert svc.read(real.id) is not None
    after = await svc.search(MemorySearchRequest(query="apples", scopes=[DEMO_SCOPE]))
    assert after.count == 0
