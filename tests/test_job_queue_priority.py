from __future__ import annotations

import asyncio
import json

import pytest

from app.job_queue import JobQueue, Priority


def _queued(tmp_path, jid: str) -> str:
    jd = tmp_path / "d" / jid
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "status.json").write_text(json.dumps({"job_id": jid, "status": "queued"}))
    return jid


async def _drain(queue: JobQueue, order: list, n: int):
    for _ in range(200):
        if queue.depth() == 0 and queue.current_job_id is None and len(order) >= n:
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_high_drains_before_low_and_fifo_within_lane(tmp_path, monkeypatch):
    import app.jobs as jobs_module

    monkeypatch.setattr(jobs_module, "JOBS_BASE", tmp_path)
    queue = JobQueue()
    await queue.start()
    try:
        order: list[str] = []
        gate = asyncio.Event()

        def mk(name: str, *, block: bool = False):
            jid = _queued(tmp_path, name)

            async def runner():
                if block:
                    await gate.wait()
                order.append(name)

            return jid, runner

        # Block the worker so the rest queue up behind it.
        b_id, b_run = mk("blocker", block=True)
        await queue.enqueue(b_id, b_run, Priority.HIGH)

        l1, l1r = mk("low1")
        l2, l2r = mk("low2")
        h1, h1r = mk("high1")
        h2, h2r = mk("high2")
        await queue.enqueue(l1, l1r, Priority.LOW)
        await queue.enqueue(l2, l2r, Priority.LOW)
        await queue.enqueue(h1, h1r, Priority.HIGH)
        await queue.enqueue(h2, h2r, Priority.HIGH)

        gate.set()
        await _drain(queue, order, 5)

        # blocker first (was running), then both HIGH (FIFO), then both LOW (FIFO).
        assert order == ["blocker", "high1", "high2", "low1", "low2"]
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_default_priority_is_high(tmp_path, monkeypatch):
    import app.jobs as jobs_module

    monkeypatch.setattr(jobs_module, "JOBS_BASE", tmp_path)
    queue = JobQueue()
    await queue.start()
    try:
        order: list[str] = []
        gate = asyncio.Event()

        async def blocker():
            await gate.wait()
            order.append("blocker")

        b = _queued(tmp_path, "blocker")
        await queue.enqueue(b, blocker, Priority.HIGH)

        low = _queued(tmp_path, "low")
        deflt = _queued(tmp_path, "default")
        await queue.enqueue(low, (lambda: _append(order, "low")), Priority.LOW)
        await queue.enqueue(deflt, (lambda: _append(order, "default")))  # no priority arg

        gate.set()
        await _drain(queue, order, 3)
        # default enqueue behaved as HIGH → ran before the LOW job.
        assert order == ["blocker", "default", "low"]
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_running_job_not_interrupted(tmp_path, monkeypatch):
    import app.jobs as jobs_module

    monkeypatch.setattr(jobs_module, "JOBS_BASE", tmp_path)
    queue = JobQueue()
    await queue.start()
    try:
        order: list[str] = []

        async def long_job():
            order.append("start")
            await asyncio.sleep(0.05)
            order.append("end")

        a = _queued(tmp_path, "A")
        await queue.enqueue(a, long_job, Priority.HIGH)
        b = _queued(tmp_path, "B")
        await queue.enqueue(b, (lambda: _append(order, "B")), Priority.HIGH)

        await _drain(queue, order, 3)
        # A ran to completion (start then end) before B popped.
        assert order == ["start", "end", "B"]
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_stop_wakes_idle_worker(tmp_path):
    queue = JobQueue()
    await queue.start()
    # No items queued: the worker is parked on the empty semaphore.
    await asyncio.wait_for(queue.stop(), timeout=2.0)
    assert queue.current_job_id is None


def _append(order: list, name: str):
    async def _run():
        order.append(name)

    return _run()
