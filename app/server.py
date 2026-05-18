from __future__ import annotations

import os
import platform
import sys
import threading
import time

import psutil

from .jobs import list_jobs

_PROCESS_START = time.monotonic()

# Prime the CPU sampler so interval=None returns a real reading from the first call
psutil.cpu_percent()

_STATUS_MAP = {"queued": "queued", "running": "running", "done": "done", "error": "failed"}
_counts_cache: dict = {"queued": 0, "running": 0, "done": 0, "failed": 0}
_counts_cache_ts: float = 0.0
_COUNTS_TTL = 5.0


def _get_job_counts() -> dict:
    global _counts_cache, _counts_cache_ts
    now = time.monotonic()
    if now - _counts_cache_ts < _COUNTS_TTL:
        return _counts_cache
    counts: dict = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    for j in list_jobs():
        mapped = _STATUS_MAP.get(j.get("status", ""))
        if mapped:
            counts[mapped] += 1
    _counts_cache = counts
    _counts_cache_ts = now
    return counts


def get_server_stats() -> dict:
    from .job_queue import get_job_queue

    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": cpu,
        "memory": {"used": mem.used, "total": mem.total, "percent": mem.percent},
        "disk": {"used": disk.used, "total": disk.total, "percent": disk.percent},
        "uptime_seconds": time.monotonic() - _PROCESS_START,
        "jobs": _get_job_counts(),
        "queue_depth": get_job_queue().depth(),
        "hostname": platform.node(),
        "python_version": sys.version.split()[0],
    }


def schedule_restart() -> None:
    def _do() -> None:
        time.sleep(0.1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_do, daemon=True).start()
