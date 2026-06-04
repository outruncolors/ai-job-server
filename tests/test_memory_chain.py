from __future__ import annotations

from types import SimpleNamespace

from app.chain.models import MemoryStepConfig
from app.chain.steps.llm import _retrieve_memory_block
from app.chain.template import render_template
from app.memory.models import MemoryScope, MemoryWriteRequest
from app.memory.service import get_service


def test_extra_token_renders_memory():
    assert render_template("X {{memory}} Y", extra={"memory": "BLOCK"}) == "X BLOCK Y"


def _ctx():
    return dict(
        request=SimpleNamespace(input="lighthouse"),
        text_output="",
        context="",
        step=SimpleNamespace(name="step"),
        step_index=1,
        step_inputs={},
        step_outputs={},
        variables={"site": "ai-job-server"},
    )


async def test_retrieve_memory_block_finds_seeded_memory():
    svc = get_service()
    await svc.write(
        MemoryWriteRequest(
            title="Lighthouse fact",
            body="The lighthouse is north of the harbor.",
            scope=MemoryScope(scope_type="project", scope_id="ai-job-server"),
        )
    )
    cfg = MemoryStepConfig(
        enabled=True,
        query="{{input}}",
        scopes=[{"scope_type": "project", "scope_id": "{{var.site}}"}],
        top_k=3,
    )
    block = await _retrieve_memory_block(cfg, **_ctx())
    assert "Lighthouse fact" in block
    assert "project/ai-job-server" in block


async def test_retrieve_memory_block_empty_when_no_match():
    cfg = MemoryStepConfig(
        enabled=True,
        query="nonexistent topic xyzzy",
        scopes=[{"scope_type": "project", "scope_id": "ai-job-server"}],
        top_k=3,
    )
    assert await _retrieve_memory_block(cfg, **_ctx()) == ""
