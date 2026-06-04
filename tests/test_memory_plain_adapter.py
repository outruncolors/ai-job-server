from __future__ import annotations

from app.memory import store
from app.memory.adapters.plain import PlainAdapter
from app.memory.models import MemoryRecord, MemoryScope

PROJECT = MemoryScope(scope_type="project", scope_id="ai-job-server")
OTHER = MemoryScope(scope_type="app", scope_id="hoodat")


def _seed(mem_id, title, body, scope=PROJECT, tags=None, status="active"):
    store.write_record(
        MemoryRecord(
            id=mem_id,
            title=title,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            tags=tags or [],
            created_at="2026-06-04T00:00:00+00:00",
            updated_at="2026-06-04T00:00:00+00:00",
            status=status,
            body=body,
        )
    )


async def test_search_finds_title_match():
    _seed("m1", "Lighthouse facts", "north of the harbor")
    _seed("m2", "Apple notes", "alice likes apples")
    res = await PlainAdapter().search("lighthouse", [PROJECT], top_k=5)
    assert res and res[0].memory_id == "m1"


async def test_search_finds_body_match():
    _seed("m1", "Notes", "the harbor has a tall lighthouse")
    res = await PlainAdapter().search("lighthouse", [PROJECT], top_k=5)
    assert res and res[0].memory_id == "m1"


async def test_search_respects_scope():
    _seed("m1", "secret", "lighthouse in hoodat", scope=OTHER)
    res = await PlainAdapter().search("lighthouse", [PROJECT], top_k=5)
    assert res == []


async def test_search_respects_top_k():
    for i in range(5):
        _seed(f"m{i}", f"apple {i}", "apples apples apples")
    res = await PlainAdapter().search("apple", [PROJECT], top_k=2)
    assert len(res) == 2


async def test_search_ignores_deleted():
    _seed("m1", "Lighthouse", "lighthouse", status="deleted")
    res = await PlainAdapter().search("lighthouse", [PROJECT], top_k=5)
    assert res == []


async def test_deterministic_ordering_on_ties():
    # identical content → tie broken by memory_id ascending
    _seed("mb", "apple", "apple")
    _seed("ma", "apple", "apple")
    res = await PlainAdapter().search("apple", [PROJECT], top_k=5)
    assert [r.memory_id for r in res] == ["ma", "mb"]
