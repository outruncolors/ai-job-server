from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

Runner = Callable[[], Awaitable[Any]]
_SENTINEL: tuple = (None, None)


class JobQueue:
    """Single-worker async queue that runs job runners sequentially.

    A "runner" is a zero-arg callable returning an awaitable — typically a
    closure around ``execute_image_job`` / ``execute_voice_job`` / ``execute_chain_job``
    bound to a specific ``job_id``. The worker pulls one runner at a time and
    awaits it to completion before pulling the next.

    The on-disk ``status.json`` for each job is the source of truth: the
    worker re-reads it before invoking the runner so a job cancelled while
    queued is silently skipped.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[Optional[str], Optional[Runner]]] = asyncio.Queue()
        self._pending_ids: set[str] = set()
        self._worker_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._current_job_id: Optional[str] = None

    async def start(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._stop_event.clear()
        self._worker_task = asyncio.create_task(self._run(), name="job-queue-worker")
        log.info("Job queue worker started")

    async def stop(self) -> None:
        """Stop the worker. The currently-running job (if any) is awaited to
        completion. Any jobs still queued in memory are abandoned — they
        remain ``"queued"`` on disk and will be re-enqueued at next startup
        by :func:`recover_jobs`.
        """
        if self._worker_task is None:
            return
        self._stop_event.set()
        await self._queue.put(_SENTINEL)
        try:
            await self._worker_task
        except Exception:  # noqa: BLE001
            log.exception("Job queue worker exited with error")
        self._worker_task = None
        log.info("Job queue worker stopped")

    async def enqueue(self, job_id: str, runner: Runner) -> None:
        if self._worker_task is None or self._worker_task.done():
            # Lazy-start in case the queue is used without going through the
            # FastAPI lifespan (tests that don't `with TestClient(app)`).
            await self.start()
        self._pending_ids.add(job_id)
        await self._queue.put((job_id, runner))
        # Yield one event-loop tick so the worker (parked on `get()`) can pick
        # this item up before the caller returns. In production the worker
        # would get scheduled anyway; in tests with TestClient the loop only
        # advances during request handling, so without this yield the worker
        # never runs.
        await asyncio.sleep(0)

    def depth(self) -> int:
        return len(self._pending_ids)

    def is_pending(self, job_id: str) -> bool:
        return job_id in self._pending_ids

    def cancel_queued(self, job_id: str) -> bool:
        """Remove ``job_id`` from in-memory pending tracking.

        The actual queue entry is dropped lazily — when the worker pops it,
        it re-checks ``status.json`` and skips anything not still
        ``"queued"``. Callers must update the job's on-disk status before
        calling this.
        """
        if job_id in self._pending_ids:
            self._pending_ids.discard(job_id)
            return True
        return False

    @property
    def current_job_id(self) -> Optional[str]:
        return self._current_job_id

    async def _run(self) -> None:
        from .jobs import find_job_dir

        while True:
            try:
                job_id, runner = await self._queue.get()
            except asyncio.CancelledError:
                return
            if job_id is None or runner is None:
                return
            if self._stop_event.is_set():
                return
            self._pending_ids.discard(job_id)

            if not _job_still_queued(find_job_dir(job_id)):
                log.info("Job queue: skipping %s (no longer queued on disk)", job_id)
                continue

            self._current_job_id = job_id
            try:
                await runner()
            except Exception:  # noqa: BLE001
                log.exception("Job queue: runner for %s raised", job_id)
            finally:
                self._current_job_id = None


def _job_still_queued(job_dir: Optional[Path]) -> bool:
    if job_dir is None:
        return False
    status_file = job_dir / "status.json"
    if not status_file.exists():
        return False
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("status") == "queued"


_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue


def reset_job_queue() -> None:
    """Test hook: drop the singleton so a fresh queue is created next call."""
    global _queue
    _queue = None


def recover_interrupted_jobs(jobs_base: Path) -> list[dict[str, Any]]:
    """Scan ``jobs_base`` for jobs left in ``running``/``queued`` state after a
    restart.

    - Any ``"running"`` job is rewritten to ``"error"`` with the reason
      ``"interrupted by server restart"`` (we can't safely resume mid-step).
    - Any ``"queued"`` job is returned in ``created_at`` order so the caller
      can re-enqueue it once the appropriate runner has been constructed.

    Returns a list of ``{job_id, job_type, job_dir, request}`` dicts for
    every queued job that survived recovery.
    """
    if not jobs_base.exists():
        return []
    queued: list[tuple[str, str, str, Path, dict]] = []
    for date_dir in sorted(jobs_base.iterdir()):
        if not date_dir.is_dir():
            continue
        for job_dir in sorted(date_dir.iterdir()):
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "status.json"
            if not status_file.exists():
                continue
            try:
                status = json.loads(status_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            s = status.get("status")
            job_id = status.get("job_id") or job_dir.name
            if s == "running":
                status["status"] = "error"
                status["error"] = "interrupted by server restart"
                status["updated_at"] = datetime.now(timezone.utc).isoformat()
                status_file.write_text(json.dumps(status, indent=2), encoding="utf-8")
                log.info("Recovery: marked %s as error (was running)", job_id)
            elif s == "queued":
                req_file = job_dir / "request.json"
                if not req_file.exists():
                    continue
                try:
                    req = json.loads(req_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                job_type = req.get("job_type") or status.get("job_type") or ""
                queued.append((status.get("created_at", ""), job_id, job_type, job_dir, req))
    queued.sort(key=lambda t: t[0])
    return [
        {"job_id": jid, "job_type": jtype, "job_dir": jd, "request": req}
        for _, jid, jtype, jd, req in queued
    ]
