from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from croniter import croniter

from ..chain.executor import execute_chain_job, patch_initial_chain_status
from ..chain.models import ChainJobRequest, ChainStep
from ..chain.sequences import list_sequences
from ..jobs import create_job, find_job_dir
from ..llm_config import get_default_as_chain_llm_config
from .persistence import list_ticks, update_tick_fields

log = logging.getLogger(__name__)

POLL_INTERVAL = 10  # seconds between scheduler ticks


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_fire(cron_expr: str, after: Optional[datetime] = None) -> datetime:
    base = after or _now()
    return croniter(cron_expr, base).get_next(datetime).replace(tzinfo=timezone.utc)


def _is_running_or_queued(job_id: str) -> bool:
    job_dir = find_job_dir(job_id)
    if job_dir is None:
        return False
    status_file = job_dir / "status.json"
    if not status_file.exists():
        return False
    try:
        status = json.loads(status_file.read_text(encoding="utf-8"))
        return status.get("status") in ("queued", "running")
    except Exception:
        return False


class TickScheduler:
    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="tick-scheduler")
        log.info("Tick scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Tick scheduler stopped")

    async def fire_tick(self, tick_id: str, force: bool = False) -> Optional[str]:
        ticks = list_ticks()
        tick = next((t for t in ticks if t["id"] == tick_id), None)
        if tick is None:
            return None
        return await self._fire(tick, force=force)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_all()
            except Exception as exc:
                log.exception("Tick scheduler loop error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_all(self) -> None:
        now = _now()
        for tick in list_ticks():
            if not tick.get("enabled", True):
                continue
            try:
                await self._maybe_fire(tick, now)
            except Exception as exc:
                log.exception("Error processing tick %s: %s", tick.get("id"), exc)

    async def _maybe_fire(self, tick: dict, now: datetime) -> None:
        cron_expr = tick.get("schedule", {}).get("cron")
        if not cron_expr:
            return

        last_fire_str = tick.get("last_fire_at")
        if last_fire_str:
            try:
                last_fire = datetime.fromisoformat(last_fire_str)
                if last_fire.tzinfo is None:
                    last_fire = last_fire.replace(tzinfo=timezone.utc)
            except ValueError:
                last_fire = None
        else:
            last_fire = None

        next_fire = _next_fire(cron_expr, after=last_fire)

        if next_fire > now:
            return

        await self._fire(tick)

    async def _fire(self, tick: dict, force: bool = False) -> Optional[str]:
        tick_id   = tick["id"]
        tick_name = tick.get("name", tick_id)
        cron_expr = tick.get("schedule", {}).get("cron", "")

        if not force:
            last_job_id = tick.get("last_job_id")
            if last_job_id and _is_running_or_queued(last_job_id):
                log.info("Tick %s: skipping — previous job %s still active", tick_name, last_job_id)
                update_tick_fields(tick_id, last_skip_reason="overlap")
                return None

        seq_id = tick.get("sequence_id")
        sequences = list_sequences()
        seq = next((s for s in sequences if s["id"] == seq_id), None)
        if seq is None:
            log.warning("Tick %s: sequence %s not found — skipping", tick_name, seq_id)
            update_tick_fields(tick_id, last_skip_reason="sequence_missing")
            return None

        try:
            llm_cfg = get_default_as_chain_llm_config()
        except RuntimeError as exc:
            log.warning("Tick %s: %s — skipping", tick_name, exc)
            update_tick_fields(tick_id, last_skip_reason="no_default_llm")
            return None

        req = ChainJobRequest(
            title=f"[tick] {tick_name}",
            input="",
            llm=llm_cfg,
            steps=[ChainStep(name=seq["name"], type="sequence", sequence_id=seq_id)],
        )

        data = create_job("chain", req.model_dump(), req.input, extra_meta={"fired_by_tick": tick_id})
        job_id  = data["job_id"]
        job_dir = find_job_dir(job_id)
        patch_initial_chain_status(job_dir, len(req.steps))
        asyncio.create_task(execute_chain_job(job_id, job_dir, req), name=f"tick-job-{job_id[:8]}")

        now     = _now()
        nxt     = _next_fire(cron_expr, after=now) if cron_expr else None
        nxt_str = nxt.isoformat() if nxt else None
        update_tick_fields(
            tick_id,
            last_fire_at=now.isoformat(),
            last_job_id=job_id,
            last_skip_reason=None,
            next_fire_at=nxt_str,
        )
        log.info("Tick %s fired → job %s", tick_name, job_id)
        return job_id


_scheduler: Optional[TickScheduler] = None


def get_scheduler() -> TickScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TickScheduler()
    return _scheduler


async def start_scheduler() -> None:
    await get_scheduler().start()


async def stop_scheduler() -> None:
    await get_scheduler().stop()
