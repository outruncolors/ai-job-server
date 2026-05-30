"""Simulation clock — fires a tick every ``TICK_INTERVAL_SECONDS``.

Clones the async-loop lifecycle of ``app/ticks/scheduler.py`` (start/stop/_loop
parked on ``asyncio.sleep``). Each fire enqueues **one LOW-priority job per
tick** so background generation never starves real (HIGH) jobs; the job's runner
drives ``tick_runner.run_tick`` over every occupant. The clock is started/stopped
in the FastAPI lifespan via ``start_sim_clock`` / ``stop_sim_clock``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from ...jobs import _write_status, create_job, find_job_dir
from . import settings_store
from .config import SIM_AUTOSTART
from .tick_runner import next_tick, run_tick

log = logging.getLogger(__name__)

TICK_JOB_TYPE = "blaboratory_tick"

# Persisted desired-state for the sim clock so a server restart resumes the
# state the operator last selected (rather than always-on or always-off).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STATE_PATH: Path = _PROJECT_ROOT / "config" / "blaboratory" / "clock_state.json"


def _read_desired() -> Optional[str]:
    """Return "running" / "stopped" / None (file absent or unreadable)."""
    if not _STATE_PATH.exists():
        return None
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        v = data.get("desired")
        return v if v in ("running", "stopped") else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_desired(state: str) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_PATH.with_suffix(_STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps({"desired": state}, indent=2), encoding="utf-8")
    os.replace(tmp, _STATE_PATH)


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

    async def start(self, *, persist: bool = True) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="blaboratory-sim-clock")
        if persist:
            _write_desired("running")
        log.info(
            "Blaboratory sim clock started (interval %ss)",
            settings_store.tick_interval_seconds(),
        )

    async def stop(self, *, persist: bool = True) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if persist:
            _write_desired("stopped")
        log.info("Blaboratory sim clock stopped")

    @property
    def running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(settings_store.tick_interval_seconds())
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


async def stop_sim_clock(*, persist: bool = True) -> None:
    if _clock is not None:
        await _clock.stop(persist=persist)


async def start_sim_clock_if_desired() -> None:
    """Boot-time auto-start: resume the operator's last desired state.

    Persisted file wins absolutely once it exists. Falls back to the
    ``BLAB_SIM_AUTOSTART`` env var on first boot (no state file yet).
    Started clocks here do **not** re-persist — the desired state hasn't
    changed.
    """
    desired = _read_desired()
    if desired == "running":
        await get_sim_clock().start(persist=False)
    elif desired is None and SIM_AUTOSTART:
        await get_sim_clock().start(persist=False)
