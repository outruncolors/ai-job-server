"""App-managed embed ``llama-server`` (D1.2a).

A *second*, always-on ``llama-server`` owned by the app on ``llm``-capable nodes,
serving ``/v1/embeddings`` on a dedicated port (default 8081). It is the sibling
of the chat :class:`~app.llamacpp.manager.LlamaCppManager` and mirrors its
lifecycle (adopt-if-running, ``/health`` readiness probe, 500-line stdout ring
buffer, ``os.killpg`` teardown) — but with a **fixed** embed preset (no
model-swap hash lock; the embedder loads one model and stays put).

The argv is fixed by config (`embed_model_path`, `embed_port`, `embed_pooling`):

    llama-server --model <embed_model_path> --embeddings --pooling <p> \
                 --host <host> --port <embed_port> --ctx-size 512 -ngl 99

bge-small wants ``--pooling cls`` (verified on LLAMA_CPP_TAG b9204); wrong
pooling silently degrades similarity.
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

from .config import LlamaCppConfig, get_config
from .manager import LlamaCppLoadError

READY_TIMEOUT = 180.0


class LlamaCppEmbedManager:
    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._adopted_pid: Optional[int] = None
        self._started_at: Optional[float] = None
        self._log_buffer: deque[str] = deque(maxlen=500)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._read_task: Optional[asyncio.Task] = None

    def _cfg(self) -> LlamaCppConfig:
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
                r = await c.get(f"http://127.0.0.1:{cfg.embed_port}/health", timeout=5.0)
                return r.status_code == 200
        except Exception:
            return False

    def _build_argv(self) -> list[str]:
        """Fixed embed-server argv from config. Raises if no model is configured."""
        cfg = self._cfg()
        if not cfg.embed_model_path:
            raise LlamaCppLoadError(
                "embed server has no model — set embed_model_path in llamacpp config"
            )
        return [
            cfg.binary_path,
            "--model",
            str(cfg.embed_model_path),
            "--embeddings",
            "--pooling",
            str(cfg.embed_pooling or "cls"),
            "--host",
            cfg.host,
            "--port",
            str(cfg.embed_port),
            "--ctx-size",
            "512",
            "-ngl",
            "99",
        ]

    async def _spawn(self, argv: list[str]) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise LlamaCppLoadError(
                f"llama.cpp binary not found at {argv[0]} — set binary_path in config"
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
            await asyncio.sleep(1.0)
        return False

    async def adopt(self) -> bool:
        """If something is already serving on the embed port, record its PID."""
        if await self._health_ok():
            if self._our_pid() is None:
                self._adopted_pid = self._find_pid_on_port(self._cfg().embed_port)
                self._started_at = time.monotonic()
            return True
        return False

    async def start(self) -> dict:
        async with self._lock:
            if await self._health_ok():
                if self._our_pid() is None:
                    self._adopted_pid = self._find_pid_on_port(self._cfg().embed_port)
                    self._started_at = time.monotonic()
                return await self._status()
            argv = self._build_argv()
            await self._spawn(argv)
            ready = await self._wait_ready(READY_TIMEOUT)
            if not ready:
                tail = "\n".join(list(self._log_buffer)[-50:])
                await self._terminate()
                raise LlamaCppLoadError(
                    f"embed server did not become healthy within {int(READY_TIMEOUT)}s"
                    f"\n--- last logs ---\n{tail}"
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
        await asyncio.sleep(1.0)
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
        uptime: Optional[float] = None
        if alive and self._started_at is not None:
            uptime = time.monotonic() - self._started_at
        return {
            "running": alive,
            "port": self._cfg().embed_port,
            "model_path": self._cfg().embed_model_path,
            "pid": self._our_pid(),
            "uptime_seconds": uptime,
        }

    async def status(self) -> dict:
        return await self._status()


_embed_manager: Optional[LlamaCppEmbedManager] = None


def get_embed_manager() -> LlamaCppEmbedManager:
    global _embed_manager
    if _embed_manager is None:
        _embed_manager = LlamaCppEmbedManager()
    return _embed_manager


def reset_embed_manager() -> None:
    """Drop the cached singleton — tests use this between cases."""
    global _embed_manager
    _embed_manager = None
