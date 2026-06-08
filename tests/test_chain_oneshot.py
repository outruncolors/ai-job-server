"""Phase 1 — run_traced_llm boilerplate extraction (executor monkeypatched)."""

from __future__ import annotations

import app.chain.oneshot as oneshot
from app.chain.models import Alternative, ChainJobRequest, ChainStep


def _req() -> ChainJobRequest:
    return ChainJobRequest(
        title="t",
        input="hello",
        steps=[
            ChainStep(
                number=1,
                id="s1",
                name="Step One",
                type="llm",
                alternatives=[Alternative(prompt="say hi")],
            )
        ],
    )


async def test_run_traced_llm(monkeypatch):
    async def fake_execute(job_id, job_dir, request):
        (job_dir / "final_output.txt").write_text("the output", encoding="utf-8")
        step_dir = job_dir / "steps" / "001_s1"
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / "prompt.txt").write_text("rendered prompt", encoding="utf-8")
        (step_dir / "output.txt").write_text("the output", encoding="utf-8")

    monkeypatch.setattr(oneshot, "execute_chain_job", fake_execute)
    result = await oneshot.run_traced_llm("tomeberry_test", _req())
    assert result.final_output == "the output"
    assert result.job_id
    assert result.job_dir is not None
    assert len(result.steps) == 1
    assert result.steps[0]["prompt"] == "rendered prompt"
    assert result.steps[0]["output"] == "the output"
    # the job dir is a real on-disk trace
    assert (result.job_dir / "request.json").exists()
