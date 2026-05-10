from __future__ import annotations

import shutil
import subprocess
from typing import Optional

import httpx

from .config import OmniVoiceConfig


class OmniVoiceManager:
    def __init__(self) -> None:
        self.desired_state: str = "stopped"
        self._proc: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self.last_error: Optional[str] = None
        self.active_voice_jobs: int = 0

    @property
    def process_state(self) -> str:
        if self._proc is None:
            return "stopped"
        rc = self._proc.poll()
        return "running" if rc is None else "stopped"

    @property
    def pid(self) -> Optional[int]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        return None

    def start(self, config: OmniVoiceConfig) -> None:
        if not config.server_command:
            raise ValueError(
                "server_command is not configured. "
                "Set it via PUT /v1/omnivoice/config before starting."
            )
        try:
            self._proc = subprocess.Popen(config.server_command)  # noqa: S603
            self.desired_state = "running"
            self.last_error = None
        except FileNotFoundError as exc:
            self.last_error = str(exc)
            raise RuntimeError(
                f"Could not start OmniVoice server: {exc}"
            ) from exc

    def stop(self) -> None:
        self.desired_state = "stopped"
        if self._proc is None or self._proc.poll() is not None:
            self._proc = None
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._proc = None

    def restart(self, config: OmniVoiceConfig) -> None:
        self.stop()
        self.start(config)

    async def health_check(self, config: OmniVoiceConfig) -> str:
        if config.mode != "persistent":
            return "unknown"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(f"{config.persistent_api_base}/health")
            return "ok"
        except (httpx.ConnectError, httpx.TimeoutException):
            return "unreachable"
        except Exception:
            return "unknown"

    def ephemeral_available(self) -> bool:
        return shutil.which("omnivoice-infer") is not None


_manager: Optional[OmniVoiceManager] = None


def get_manager() -> OmniVoiceManager:
    global _manager
    if _manager is None:
        _manager = OmniVoiceManager()
    return _manager
