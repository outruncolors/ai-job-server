"""One-shot traced chain execution — the create_job → execute → read boilerplate.

Prattletale (and Hoodat/Blaboratory) all drive the chain executor *directly*
(synchronously, no JobQueue) for foreground LLM work, then read
``final_output.txt`` back. This extracts that duplicated dance into one helper so
new consumers (Tomeberry) don't re-implement it. The on-disk job dir
(``/srv/ai-jobs/<date>/<job_id>/``) remains a free, deep trace cross-linkable from
an app's own trace record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..jobs import create_job, find_job_dir
from .executor import execute_chain_job
from .models import ChainJobRequest


@dataclass
class TracedResult:
    job_id: str
    job_dir: Optional[Path]
    final_output: str
    steps: list[dict] = field(default_factory=list)


def _read_final_output(job_dir: Path) -> str:
    p = job_dir / "final_output.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def collect_steps(job_dir: Path, request: ChainJobRequest) -> list[dict]:
    """Pair the request's ordered steps with the outputs the executor wrote under
    ``steps/NNN_<id>/`` so a trace is self-describing. Best-effort — a step whose
    files can't be read records that field as ``None`` rather than failing.
    """
    steps_dir = job_dir / "steps"
    collected: list[dict] = []
    for step in request.steps:
        alt = step.alternatives[0] if step.alternatives else None
        rendered_prompt = alt.prompt if alt is not None else None
        output: Optional[str] = None
        memory: Optional[str] = None
        step_dir = steps_dir / f"{step.number:03d}_{step.id}"
        if step_dir.is_dir():
            prompt_file = step_dir / "prompt.txt"
            if prompt_file.exists():
                rendered_prompt = prompt_file.read_text(encoding="utf-8")
            output_file = step_dir / "output.txt"
            if output_file.exists():
                output = output_file.read_text(encoding="utf-8")
            memory_file = step_dir / "memory.txt"
            if memory_file.exists():
                memory = memory_file.read_text(encoding="utf-8")
        collected.append(
            {
                "number": step.number,
                "id": step.id,
                "name": step.name,
                "prompt": rendered_prompt,
                "output": output,
                "memory": memory,
            }
        )
    return collected


async def run_traced_llm(
    job_type: str,
    request: ChainJobRequest,
    *,
    extra_meta: Optional[dict] = None,
) -> TracedResult:
    """Create a job, run it through the chain executor, and read the result.

    Returns a :class:`TracedResult` carrying the job id, job dir, the final output
    text, and the per-step prompt/output trace. Raises whatever the executor
    raises — callers that need prattletale-style "never crash the turn" discipline
    wrap this in their own try/except and post an error message on failure.
    """
    status = create_job(job_type, request.model_dump(), request.input, extra_meta)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover — create_job just made it
        raise RuntimeError(f"job directory disappeared for {job_id}")
    await execute_chain_job(job_id, job_dir, request)
    return TracedResult(
        job_id=job_id,
        job_dir=job_dir,
        final_output=_read_final_output(job_dir),
        steps=collect_steps(job_dir, request),
    )
