from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import psutil
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .jobs import list_jobs

_PROCESS_START = time.monotonic()

# Prime the CPU sampler so interval=None returns a real reading from the first call
psutil.cpu_percent()

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
SERVER_CONFIG_PATH: Path = Path(
    os.environ.get(
        "AI_JOB_SERVER_CONFIG_PATH",
        str(PROJECT_ROOT / "config" / "server.json"),
    )
)


class Peer(BaseModel):
    name: str
    host: str
    port: int = 8090
    capabilities: list[str] = Field(default_factory=list)


class ServerConfig(BaseModel):
    role: str = "primary"
    # Default to all-capabilities so single-machine deploys without a config file
    # behave exactly as before. A real multi-machine setup writes config/server.json.
    capabilities: list[str] = Field(
        default_factory=lambda: ["web", "voice", "image", "llm"]
    )
    peers: list[Peer] = Field(default_factory=list)


_server_config: Optional[ServerConfig] = None


def load_server_config() -> ServerConfig:
    global _server_config
    try:
        if SERVER_CONFIG_PATH.exists():
            data = json.loads(SERVER_CONFIG_PATH.read_text(encoding="utf-8"))
            _server_config = ServerConfig(**data)
            return _server_config
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    _server_config = ServerConfig()
    return _server_config


def get_server_config() -> ServerConfig:
    global _server_config
    if _server_config is None:
        return load_server_config()
    return _server_config


def reset_server_config() -> None:
    """Drop cached config so the next get_server_config() reloads from disk.

    Tests monkeypatch SERVER_CONFIG_PATH then call this to pick up the new path.
    """
    global _server_config
    _server_config = None


def get_local_capabilities() -> set[str]:
    return set(get_server_config().capabilities)


def get_peers() -> list[Peer]:
    return list(get_server_config().peers)


def find_peer_for_capability(cap: str) -> Optional[Peer]:
    for p in get_peers():
        if cap in p.capabilities:
            return p
    return None


_git_sha_cache: Optional[str] = None
_git_sha_loaded = False


def get_git_sha() -> Optional[str]:
    global _git_sha_cache, _git_sha_loaded
    if _git_sha_loaded:
        return _git_sha_cache
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            _git_sha_cache = sha or None
    except (OSError, subprocess.SubprocessError):
        _git_sha_cache = None
    _git_sha_loaded = True
    return _git_sha_cache


def requires_capability(cap: str) -> Callable[[], None]:
    """FastAPI dependency factory: 503s when this node lacks ``cap``.

    Routes that perform local work needing a capability should declare
    ``dependencies=[Depends(requires_capability("image"))]``. Routes that only
    *call out* to a peer should not — the peer holds the capability.
    """

    def _dep() -> None:
        if cap in get_local_capabilities():
            return
        peer = find_peer_for_capability(cap)
        where = peer.host if peer else "unknown"
        raise HTTPException(
            status_code=503,
            detail={
                "error": "capability_unavailable",
                "needed": cap,
                "where": where,
            },
        )

    return _dep

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
