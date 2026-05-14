from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path
from typing import Optional

import psutil

from .client import ComfyUIClient
from .config import ComfyUIConfig, get_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = PROJECT_ROOT / "config"


class ComfyUIManager:
    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._adopted_pid: Optional[int] = None
        self._started_at: Optional[float] = None
        self._lock: asyncio.Lock = asyncio.Lock()

    def _cfg(self) -> ComfyUIConfig:
        return get_config()

    def _client(self) -> ComfyUIClient:
        cfg = self._cfg()
        return ComfyUIClient(f"http://{cfg.host}:{cfg.port}")

    def _build_argv(self) -> list[str]:
        cfg = self._cfg()
        argv = [
            cfg.venv_python,
            "main.py",
            "--listen", cfg.host,
            "--port", str(cfg.port),
            "--disable-auto-launch",
            "--preview-method", cfg.preview_method,
            "--output-directory", cfg.output_dir,
            "--input-directory", cfg.input_dir,
            f"--{cfg.vram_mode}",
            "--reserve-vram", str(cfg.reserve_vram_gb),
            "--cuda-malloc",
        ]
        if cfg.extra_model_paths_yaml and Path(cfg.extra_model_paths_yaml).exists():
            argv += ["--extra-model-paths-config", cfg.extra_model_paths_yaml]
        if cfg.use_sage_attention:
            argv.append("--use-sage-attention")
        argv.extend(cfg.extra_args)
        return argv

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

    async def _is_alive(self) -> bool:
        try:
            await self._client().system_stats()
            return True
        except Exception:
            return False

    async def _wait_ready(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                stats = await self._client().system_stats()
                if stats.get("devices"):
                    return
            except Exception:
                pass
            await asyncio.sleep(2.0)
        raise TimeoutError(f"ComfyUI did not become ready within {timeout:.0f}s")

    async def start(self) -> dict:
        async with self._lock:
            if await self._is_alive():
                # Adopt whatever is already running
                if self._our_pid() is None:
                    pid = self._find_pid_on_port(self._cfg().port)
                    self._adopted_pid = pid
                    self._started_at = time.monotonic()
                return await self.status()

            cfg = self._cfg()
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            stdout_log = open(_LOG_DIR / "comfyui-server.stdout.log", "ab")
            stderr_log = open(_LOG_DIR / "comfyui-server.stderr.log", "ab")
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *self._build_argv(),
                    cwd=cfg.comfyui_root,
                    stdout=stdout_log,
                    stderr=stderr_log,
                    start_new_session=True,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"ComfyUI not found — check comfyui_root ({cfg.comfyui_root}) "
                    f"and venv_python ({cfg.venv_python}) in config"
                ) from exc
            finally:
                stdout_log.close()
                stderr_log.close()
            self._adopted_pid = None
            self._started_at = time.monotonic()

        # Wait for readiness outside the lock
        await self._wait_ready(timeout=120.0)
        return await self.status()

    async def stop(self, graceful_timeout: float = 15.0) -> dict:
        async with self._lock:
            if not self._proc_is_running() and not await self._is_alive():
                self._proc = None
                self._adopted_pid = None
                self._started_at = None
                return {"running": False}

            # 1. Ask ComfyUI to stop current work
            try:
                await self._client().interrupt()
            except Exception:
                pass

            # 2. Wait briefly for queue to drain
            deadline = time.monotonic() + min(graceful_timeout, 10.0)
            while time.monotonic() < deadline:
                try:
                    q = await self._client().queue()
                    remaining = q.get("queue_running", [])
                    if not remaining:
                        break
                except Exception:
                    break
                await asyncio.sleep(1.0)

            # 3. SIGTERM the process group
            pid = self._our_pid()
            if pid:
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass

            # 4. Wait up to 10s, then SIGKILL
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
            self._proc = None
            self._adopted_pid = None
            self._started_at = None

        # Give GPU memory time to release
        await asyncio.sleep(2.0)
        return {"running": False}

    async def restart(self) -> dict:
        await self.stop()
        return await self.start()

    async def status(self) -> dict:
        alive = await self._is_alive()
        pid = self._our_pid()
        uptime: Optional[float] = None
        if alive and self._started_at is not None:
            uptime = time.monotonic() - self._started_at
        gpu: Optional[dict] = None
        queue_remaining = 0
        if alive:
            try:
                stats = await self._client().system_stats()
                devices = stats.get("devices", [])
                if devices:
                    d = devices[0]
                    gpu = {
                        "name": d.get("name", ""),
                        "vram_total": d.get("vram_total", 0),
                        "vram_free": d.get("vram_free", 0),
                        "torch_vram_total": d.get("torch_vram_total", 0),
                        "torch_vram_free": d.get("torch_vram_free", 0),
                    }
            except Exception:
                pass
            try:
                q = await self._client().queue()
                queue_remaining = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
            except Exception:
                pass

        return {
            "running": alive,
            "pid": pid,
            "uptime_seconds": uptime,
            "port": self._cfg().port,
            "gpu": gpu,
            "queue_remaining": queue_remaining,
        }


_manager: Optional[ComfyUIManager] = None


def get_manager() -> ComfyUIManager:
    global _manager
    if _manager is None:
        _manager = ComfyUIManager()
    return _manager
