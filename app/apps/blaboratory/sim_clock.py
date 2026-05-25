"""Simulation clock — fires a tick every ``TICK_INTERVAL_SECONDS``.

Clones the async-loop lifecycle of ``app/ticks/scheduler.py`` (start/stop/_loop
parked on ``asyncio.sleep``). Each fire enqueues **one LOW-priority job per
tick** so background generation never starves real (HIGH) jobs; the job's runner
drives ``tick_runner.run_tick`` over every occupant. The clock is started/stopped
in the FastAPI lifespan via ``start_sim_clock`` / ``stop_sim_clock``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ...jobs import _write_status, create_job, find_job_dir
from .config import TICK_INTERVAL_SECONDS
from .tick_runner import next_tick, run_tick

log = logging.getLogger(__name__)

TICK_JOB_TYPE = "blaboratory_tick"


async def _run_tick_job(job_id: str, tick: int) -> None:
    """Job runner: drive one tick, owning its own status writes."""
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        return
    _write_status(job_dir, "running")
    try:
        summary = await run_tick(tick)
        (job_dir / "final_output.txt").write_text(
            f"tick {summary['tick']}: {len(summary['acted'])} acted", encoding="utf-8"
        )
        _write_status(job_dir, "done")
    except Exception as exc:  # noqa: BLE001
        log.exception("Blaboratory tick job %s failed", job_id)
        _write_status(job_dir, "error", error=str(exc))


async def fire_tick(tick: Optional[int] = None) -> str:
    """Create + enqueue (LOW lane) a job that runs one tick. Returns the job id."""
    from ...job_queue import Priority, get_job_queue

    if tick is None:
        tick = next_tick()
    status = create_job(TICK_JOB_TYPE, {"tick": tick}, "", extra_meta={"tick": tick})
    job_id = status["job_id"]

    async def _runner():
        await _run_tick_job(job_id, tick)

    await get_job_queue().enqueue(job_id, _runner, Priority.LOW)
    return job_id


class SimClock:
    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="blaboratory-sim-clock")
        log.info("Blaboratory sim clock started (interval %ss)", TICK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Blaboratory sim clock stopped")

    @property
    def running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(TICK_INTERVAL_SECONDS)
            if not self._running:
                break
            try:
                await fire_tick()
            except Exception:  # noqa: BLE001
                log.exception("Blaboratory sim clock: failed to fire tick")


_clock: Optional[SimClock] = None


def get_sim_clock() -> SimClock:
    global _clock
    if _clock is None:
        _clock = SimClock()
    return _clock


async def start_sim_clock() -> None:
    await get_sim_clock().start()


async def stop_sim_clock() -> None:
    if _clock is not None:
        await _clock.stop()
