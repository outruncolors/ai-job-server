from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

JOBS_BASE = Path(os.environ.get("JOBS_BASE", "/srv/ai-jobs"))


def _today_dir() -> Path:
    return JOBS_BASE / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _find_job_dir(job_id: str) -> Optional[Path]:
    """Search all date directories for a job_id."""
    if not JOBS_BASE.exists():
        return None
    for date_dir in sorted(JOBS_BASE.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        job_dir = date_dir / job_id
        if job_dir.is_dir():
            return job_dir
    return None


def create_job(job_type: str, request_data: dict[str, Any], input_text: str) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    job_dir = _today_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    status = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "queued",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "error": None,
    }

    (job_dir / "request.json").write_text(
        json.dumps({"job_type": job_type, **request_data}, indent=2), encoding="utf-8"
    )
    (job_dir / "input.txt").write_text(input_text, encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    (job_dir / "logs.txt").write_text("", encoding="utf-8")
    (job_dir / "artifacts.json").write_text("[]", encoding="utf-8")

    return status


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    job_dir = _find_job_dir(job_id)
    if job_dir is None:
        return None
    status_file = job_dir / "status.json"
    if not status_file.exists():
        return None
    return json.loads(status_file.read_text(encoding="utf-8"))


def list_jobs() -> list[dict[str, Any]]:
    if not JOBS_BASE.exists():
        return []
    jobs = []
    for date_dir in sorted(JOBS_BASE.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for job_dir in sorted(date_dir.iterdir(), reverse=True):
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if status_file.exists():
                jobs.append(json.loads(status_file.read_text(encoding="utf-8")))
    return jobs


def clear_pending_jobs() -> int:
    import shutil
    if not JOBS_BASE.exists():
        return 0
    removed = 0
    for date_dir in JOBS_BASE.iterdir():
        if not date_dir.is_dir():
            continue
        for job_dir in date_dir.iterdir():
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if not status_file.exists():
                continue
            status = json.loads(status_file.read_text(encoding="utf-8"))
            if status.get("status") == "queued":
                shutil.rmtree(job_dir)
                removed += 1
    return removed


def get_job_file(job_id: str, filename: str) -> Optional[Path]:
    job_dir = _find_job_dir(job_id)
    if job_dir is None:
        return None
    # Restrict to files that actually live inside the job directory.
    target = (job_dir / filename).resolve()
    if not str(target).startswith(str(job_dir.resolve())):
        return None
    if not target.exists() or target.is_dir():
        return None
    return target
