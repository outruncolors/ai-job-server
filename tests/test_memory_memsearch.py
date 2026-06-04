"""memsearch adapter integration tests.

Skipped entirely unless ``memsearch`` is importable, so the normal suite never goes
flaky / never triggers the bge-m3 model download. These tests DO download the embedding
model on first run, so they are also gated behind an opt-in env flag.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("memsearch")

if not os.environ.get("MEMORY_MEMSEARCH_TEST"):
    pytest.skip(
        "set MEMORY_MEMSEARCH_TEST=1 to run memsearch integration tests "
        "(downloads the bge-m3 ONNX model on first run)",
        allow_module_level=True,
    )

from app.memory import config as mcfg  # noqa: E402
from app.memory import store  # noqa: E402
from app.memory.adapters.memsearch import MemsearchAdapter  # noqa: E402
from app.memory.models import MemoryRecord, MemoryScope  # noqa: E402

SCOPE = MemoryScope(scope_type="project", scope_id="ai-job-server")


def _seed(mem_id, title, body, scope=SCOPE, status="active"):
    store.write_record(
        MemoryRecord(
            id=mem_id,
            title=title,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            created_at="2026-06-04T00:00:00+00:00",
            updated_at="2026-06-04T00:00:00+00:00",
            status=status,
            body=body,
        )
    )


def _adapter():
    return MemsearchAdapter(mcfg.get_config())


async def test_health():
    h = await _adapter().health()
    assert h.backend == "memsearch"
    assert h.index_available is True


async def test_index_and_search():
    _seed("m1", "Lighthouse", "The lighthouse is north of the harbor.")
    _seed("m2", "Apples", "Alice likes red apples.")
    ad = _adapter()
    res = await ad.index([store.base_dir()], force=True)
    assert res.indexed_files >= 1
    hits = await ad.search("where is the lighthouse", [SCOPE], top_k=3)
    assert hits and hits[0].memory_id == "m1"


async def test_search_ignores_deleted():
    _seed("m1", "Lighthouse", "The lighthouse is north of the harbor.", status="deleted")
    ad = _adapter()
    await ad.index([store.base_dir()], force=True)
    hits = await ad.search("lighthouse", [SCOPE], top_k=3)
    assert all(h.memory_id != "m1" for h in hits)
