from __future__ import annotations

import pytest

from app.memory import store
from app.memory.models import MemoryRecord, MemoryScope
from app.memory.store import UnsafeMemoryId


def _record(**kw) -> MemoryRecord:
    base = dict(
        id="mem_test_001",
        title="A title",
        scope_type="project",
        scope_id="ai-job-server",
        created_at="2026-06-04T00:00:00+00:00",
        updated_at="2026-06-04T00:00:00+00:00",
        status="active",
        body="The body text.",
    )
    base.update(kw)
    return MemoryRecord(**base)


def test_write_then_read_roundtrips():
    rec = _record(tags=["a", "b"], importance=0.7)
    store.write_record(rec)
    found = store.read_record("mem_test_001")
    assert found is not None
    back, path = found
    assert back.id == rec.id
    assert back.title == rec.title
    assert back.tags == ["a", "b"]
    assert back.importance == 0.7
    assert path.exists()


def test_body_preserved_byte_exact():
    body = "line 1\n\n  indented\n---\nnot frontmatter\ntrailing no newline"
    rec = _record(body=body)
    store.write_record(rec)
    back, _ = store.read_record("mem_test_001")
    assert back.body == body


def test_update_record():
    store.write_record(_record())
    rec, _ = store.read_record("mem_test_001")
    rec.title = "Changed"
    store.write_record(rec)
    back, _ = store.read_record("mem_test_001")
    assert back.title == "Changed"


def test_soft_delete_marks_status():
    store.write_record(_record())
    rec, _ = store.read_record("mem_test_001")
    rec.status = "deleted"
    store.write_record(rec)
    back, _ = store.read_record("mem_test_001")
    assert back.status == "deleted"
    # excluded from active listings
    active = store.list_records([MemoryScope(scope_type="project", scope_id="ai-job-server")])
    assert all(r.id != "mem_test_001" for r, _ in active)


def test_list_records_by_scope():
    store.write_record(_record(id="mem_a", scope_type="app", scope_id="hoodat"))
    store.write_record(_record(id="mem_b", scope_type="app", scope_id="prattletale"))
    hoodat = store.list_records([MemoryScope(scope_type="app", scope_id="hoodat")])
    ids = {r.id for r, _ in hoodat}
    assert ids == {"mem_a"}


def test_global_scope_is_flat():
    rec = _record(id="mem_g", scope_type="global", scope_id="global")
    path = store.write_record(rec)
    assert path.parent.name == "global"


def test_reject_unsafe_memory_id():
    with pytest.raises(UnsafeMemoryId):
        store.validate_memory_id("../escape")
    with pytest.raises(UnsafeMemoryId):
        store.find_path("a/b")


def test_scope_id_traversal_is_neutralized():
    # a malicious scope_id is slugified, so it cannot escape the base dir
    rec = _record(id="mem_x", scope_type="custom", scope_id="../../etc")
    path = store.write_record(rec)
    assert store.base_dir().resolve() in path.resolve().parents
