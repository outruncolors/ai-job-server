"""MCPManager — supervises the MCP gateway process (``python -m app.mcp.gateway``).

Mirrors ``app/llamacpp/manager.py`` / ``app/comfyui/manager.py``: a singleton that
spawns the gateway in its own session (process group), health-checks it on the
data-plane port, adopts an already-running instance on boot, and tears it down
SIGTERM→SIGKILL on its process group. The app/main.py lifespan calls
``adopt() or start()`` on startup and ``stop()`` on shutdown, so the gateway comes
up with the machine via the existing systemd unit — no new unit required.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections import deque
from typing import Optional

import httpx
import psutil

from .config import MCPConfig, get_config


class MCPGatewayError(RuntimeError):
    """Raised when the gateway fails to become healthy in time."""


class MCPManager:
    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._adopted_pid: Optional[int] = None
        self._started_at: Optional[float] = None
        self._log_buffer: deque[str] = deque(maxlen=500)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._read_task: Optional[asyncio.Task] = None

    def _cfg(self) -> MCPConfig:
        return get_config()

    def _our_pid(self) -> Optional[int]:
        if self._proc is not None:
            return self._proc.pid
        return self._adopted_pid

    def _find_pid_on_port(self, port: int) -> Optional[int]:
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if conn.status == "LISTEN" and conn.laddr.port == port:
                    return conn.pid
        except (psutil.AccessDenied, PermissionError):
            pass
        return None

    def _proc_is_running(self) -> bool:
        if self._proc is not None:
            return self._proc.returncode is None
        if self._adopted_pid is not None:
            try:
                return psutil.pid_exists(self._adopted_pid)
            except Exception:
                pass
        return False

    async def _health_ok(self) -> bool:
        cfg = self._cfg()
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"http://127.0.0.1:{cfg.port}/health", timeout=5.0)
                return r.status_code == 200
        except Exception:
            return False

    def _build_argv(self) -> list[str]:
        cfg = self._cfg()
        return [cfg.python, "-m", cfg.entrypoint]

    async def _spawn(self, argv: list[str]) -> None:
        from . import config as cfg_mod
        from .config import PROJECT_ROOT

        # The gateway is a *separate* process: hand it the exact config/roster
        # paths this manager is configured with (so tests' tmp paths — and any
        # MCP_CONFIG_PATH override — reach the child, not just the real defaults).
        env = {
            **os.environ,
            "MCP_CONFIG_PATH": str(cfg_mod.CONFIG_PATH),
            "MCP_SERVERS_PATH": str(cfg_mod.SERVERS_PATH),
        }
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise MCPGatewayError(
                f"gateway python not found at {argv[0]} — set 'python' in config/mcp.json"
            ) from exc
        self._adopted_pid = None
        self._started_at = time.monotonic()
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                self._log_buffer.append(line.decode("utf-8", errors="replace").rstrip("\n"))
        except (asyncio.CancelledError, Exception):
            return

    async def _terminate(self) -> None:
        pid = self._our_pid()
        if pid:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not self._proc_is_running():
                break
            await asyncio.sleep(0.5)
        if self._proc_is_running() and pid:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        if self._proc is not None:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None
        self._proc = None
        self._adopted_pid = None
        self._started_at = None

    async def _wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self._health_ok():
                return True
            await asyncio.sleep(0.5)
        return False

    async def adopt(self) -> bool:
        """If a gateway is already serving on our port, record its PID + return True."""
        if await self._health_ok():
            if self._our_pid() is None:
                self._adopted_pid = self._find_pid_on_port(self._cfg().port)
                self._started_at = time.monotonic()
            return True
        return False

    async def start(self) -> dict:
        async with self._lock:
            if await self._health_ok():
                if self._our_pid() is None:
                    self._adopted_pid = self._find_pid_on_port(self._cfg().port)
                    self._started_at = time.monotonic()
                return await self._status()
            await self._spawn(self._build_argv())
            ready = await self._wait_ready(30.0)
            if not ready:
                tail = "\n".join(list(self._log_buffer)[-50:])
                await self._terminate()
                raise MCPGatewayError(
                    f"MCP gateway did not become healthy within 30s\n--- last logs ---\n{tail}"
                )
            return await self._status()

    async def stop(self) -> dict:
        async with self._lock:
            if not self._proc_is_running() and not await self._health_ok():
                self._proc = None
                self._adopted_pid = None
                self._started_at = None
                return {"running": False}
            await self._terminate()
        await asyncio.sleep(0.5)
        return {"running": False}

    async def restart(self) -> dict:
        await self.stop()
        return await self.start()

    def get_logs(self, tail: int = 200) -> list[str]:
        lines = list(self._log_buffer)
        if tail is None or tail <= 0:
            return lines
        return lines[-tail:]

    async def _status(self) -> dict:
        alive = await self._health_ok()
        pid = self._our_pid()
        uptime: Optional[float] = None
        if alive and self._started_at is not None:
            uptime = time.monotonic() - self._started_at
        return {
            "running": alive,
            "port": self._cfg().port,
            "pid": pid,
            "uptime_seconds": uptime,
        }

    async def status(self) -> dict:
        return await self._status()


_manager: Optional[MCPManager] = None


def get_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


def reset_manager() -> None:
    """Drop the cached singleton — tests use this between cases."""
    global _manager
    _manager = None
