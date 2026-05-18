"""Background peer health poller.

Every ``POLL_INTERVAL_SECONDS`` (30s) the poller hits each peer's
``/v1/server/health`` and stores a per-peer status in an in-memory snapshot.

Status rules:
- ``green``  — peer reachable and ``git_sha`` matches this node's.
- ``amber``  — peer reachable but ``git_sha`` differs (or either side has no SHA).
- ``red``    — peer unreachable or 5xx within the 5s HTTP timeout.

``last_seen`` and ``git_sha`` are preserved across failed polls so the UI can
still show the most recent known state alongside the current red status.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from .server import get_git_sha, get_peers

POLL_INTERVAL_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 5

_health: dict[str, dict] = {}
_task: Optional[asyncio.Task] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def poll_once() -> None:
    """Poll every configured peer once and update the in-memory snapshot."""
    local_sha = get_git_sha()
    peers = get_peers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for p in peers:
            prev = _health.get(p.name, {})
            url = f"http://{p.host}:{p.port}/v1/server/health"
            entry: dict = {"host": p.host, "port": p.port}
            try:
                r = await client.get(url)
                if r.status_code >= 500:
                    entry.update(
                        status="red",
                        git_sha=prev.get("git_sha"),
                        last_seen=prev.get("last_seen"),
                        error=f"HTTP {r.status_code}",
                    )
                else:
                    data = r.json()
                    peer_sha = data.get("git_sha")
                    if local_sha and peer_sha and peer_sha == local_sha:
                        status = "green"
                    else:
                        status = "amber"
                    entry.update(
                        status=status,
                        git_sha=peer_sha,
                        last_seen=_now_iso(),
                        error=None,
                    )
            except (httpx.HTTPError, ValueError, OSError) as exc:
                entry.update(
                    status="red",
                    git_sha=prev.get("git_sha"),
                    last_seen=prev.get("last_seen"),
                    error=str(exc) or type(exc).__name__,
                )
            _health[p.name] = entry

    # Drop entries for peers that have been removed from config.
    current = {p.name for p in peers}
    for stale in [n for n in _health if n not in current]:
        del _health[stale]


async def _loop() -> None:
    while True:
        try:
            await poll_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let a single bad poll kill the loop.
            pass
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def start_peer_poller() -> None:
    """Idempotent: start the background poll loop if it isn't running."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())


async def stop_peer_poller() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None


def get_peer_health_snapshot() -> dict[str, dict]:
    """Return a copy of the per-peer status dict so callers can mutate freely."""
    return {k: dict(v) for k, v in _health.items()}


def reset_peer_health() -> None:
    """Test helper: clear the in-memory snapshot."""
    _health.clear()
