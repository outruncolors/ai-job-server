from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import time
from collections import deque
from typing import Optional

import httpx
import psutil

from .config import LlamaCppConfig, get_config


class LlamaCppLoadError(RuntimeError):
    """Raised when a llama.cpp instance fails to become healthy in time."""


def _stable_hash(preset: dict) -> str:
    blob = json.dumps(preset, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class LlamaCppManager:
    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._adopted_pid: Optional[int] = None
        self._started_at: Optional[float] = None
        self._current_hash: Optional[str] = None
        self._current_preset: Optional[dict] = None
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
                r = await c.get(f"http://127.0.0.1:{cfg.port}/health", timeout=5.0)
                return r.status_code == 200
        except Exception:
            return False

    def _args_from_preset(self, preset: dict) -> list[str]:
        cfg = self._cfg()
        argv: list[str] = [cfg.binary_path]
        model_path = preset.get("model_path") or preset.get("model")
        if model_path:
            argv += ["--model", str(model_path)]
        argv += ["--host", "127.0.0.1", "--port", str(cfg.port)]
        args = preset.get("args") or {}
        for k, v in args.items():
            flag = "--" + str(k).replace("_", "-")
            if v is None:
                continue
            if isinstance(v, bool):
                if v:
                    argv.append(flag)
            else:
                argv += [flag, str(v)]
        return argv

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
                self._log_buffer.append(
                    line.decode("utf-8", errors="replace").rstrip("\n")
                )
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
        """If something is already serving on our port, record its PID and return True."""
        if await self._health_ok():
            if self._our_pid() is None:
                self._adopted_pid = self._find_pid_on_port(self._cfg().port)
                self._started_at = time.monotonic()
            return True
        return False

    async def start(self, preset: Optional[dict] = None) -> dict:
        async with self._lock:
            if await self._health_ok():
                if self._our_pid() is None:
                    self._adopted_pid = self._find_pid_on_port(self._cfg().port)
                    self._started_at = time.monotonic()
                return await self._status()
            if preset is None:
                raise LlamaCppLoadError(
                    "start() requires a preset when llama.cpp is not already running"
                )
            argv = self._args_from_preset(preset)
            await self._spawn(argv)
            ready = await self._wait_ready(180.0)
            if not ready:
                tail = "\n".join(list(self._log_buffer)[-50:])
                await self._terminate()
                self._current_hash = None
                self._current_preset = None
                raise LlamaCppLoadError(
                    f"llama.cpp did not become healthy within 180s\n--- last logs ---\n{tail}"
                )
            self._current_hash = _stable_hash(preset)
            self._current_preset = dict(preset)
            return await self._status()

    async def stop(self) -> dict:
        async with self._lock:
            if not self._proc_is_running() and not await self._health_ok():
                self._proc = None
                self._adopted_pid = None
                self._started_at = None
                self._current_hash = None
                self._current_preset = None
                return {"running": False}
            await self._terminate()
            self._current_hash = None
            self._current_preset = None
        await asyncio.sleep(1.0)
        return {"running": False}

    async def restart(self, preset: Optional[dict] = None) -> dict:
        await self.stop()
        if preset is None and self._current_preset is not None:
            preset = self._current_preset
        return await self.start(preset=preset)

    async def ensure_loaded(self, preset: dict) -> dict:
        hash_key = _stable_hash(preset)
        if hash_key == self._current_hash and await self._health_ok():
            return {"loaded": True, "hash": hash_key, "swapped": False}
        async with self._lock:
            if hash_key == self._current_hash and await self._health_ok():
                return {"loaded": True, "hash": hash_key, "swapped": False}
            if self._proc_is_running() or await self._health_ok():
                await self._terminate()
            argv = self._args_from_preset(preset)
            await self._spawn(argv)
            ready = await self._wait_ready(180.0)
            if not ready:
                tail = "\n".join(list(self._log_buffer)[-50:])
                await self._terminate()
                self._current_hash = None
                self._current_preset = None
                raise LlamaCppLoadError(
                    f"llama.cpp did not become healthy within 180s\n--- last logs ---\n{tail}"
                )
            self._current_hash = hash_key
            self._current_preset = dict(preset)
            return {"loaded": True, "hash": hash_key, "swapped": True}

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
            "loaded": alive and self._current_hash is not None,
            "running": alive,
            "current_preset_hash": self._current_hash,
            "port": self._cfg().port,
            "pid": pid,
            "uptime_seconds": uptime,
        }

    async def status(self) -> dict:
        return await self._status()


_manager: Optional[LlamaCppManager] = None


def get_manager() -> LlamaCppManager:
    global _manager
    if _manager is None:
        _manager = LlamaCppManager()
    return _manager


def reset_manager() -> None:
    """Drop the cached singleton — tests use this between cases."""
    global _manager
    _manager = None
