"""Trigger the deploy scripts from the running FastAPI process.

Two scripts share this runner:

- ``scripts/deploy-secondary.sh`` pushes master to the bare repo on a peer,
  SSHes in to pull + restart the peer's systemd unit, and finally restarts the
  local service so its self-reported git_sha refreshes.
- ``scripts/deploy_all`` (the Quick Actions > Catch-Up action) commits the
  working tree, folds the active branch into master, publishes to origin +
  GitHub, then *composes* deploy-secondary.sh.

Both end by restarting the local service, which kills the FastAPI process this
module lives in, so the in-memory state here is intentionally ephemeral — by
the time it's gone, the user is looking at the freshly restarted process anyway.

One run at a time (either script). Output streams into a bounded deque; the UI
polls ``GET /v1/server/deploy-status`` until status flips out of "running".
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

from .server import PROJECT_ROOT

SCRIPT_PATH: Path = PROJECT_ROOT / "scripts" / "deploy-secondary.sh"
DEPLOY_ALL_PATH: Path = PROJECT_ROOT / "scripts" / "deploy_all"


class DeployRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=500)
        self._status: str = "idle"  # idle | running | done | error
        self._exit_code: Optional[int] = None
        self._started_at: Optional[float] = None
        self._ended_at: Optional[float] = None
        self._label: Optional[str] = None
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "exit_code": self._exit_code,
                "started_at": self._started_at,
                "ended_at": self._ended_at,
                "label": self._label,
                "lines": list(self._lines),
            }

    def is_running(self) -> bool:
        with self._lock:
            return self._status == "running"

    def start_secondary(self, peer_host: Optional[str] = None) -> dict:
        """Run deploy-secondary.sh (optionally targeting a specific peer)."""
        peer_host = (peer_host or "").strip() or None
        args = [peer_host] if peer_host else []
        return self.start(script=SCRIPT_PATH, args=args, label="deploy-secondary.sh")

    def start_all(self, message: str, peer_host: Optional[str] = None) -> dict:
        """Run deploy_all: commit + merge + publish + deploy-secondary."""
        message = (message or "").strip()
        if not message:
            raise ValueError("a commit message is required")
        peer_host = (peer_host or "").strip() or None
        args = [message] + ([peer_host] if peer_host else [])
        return self.start(script=DEPLOY_ALL_PATH, args=args, label="deploy_all")

    def start(self, *, script: Path, args: list[str], label: str) -> dict:
        if not script.is_file():
            raise FileNotFoundError(f"deploy script not found: {script}")

        with self._lock:
            if self._status == "running":
                raise RuntimeError("a deploy is already running")
            self._lines.clear()
            self._status = "running"
            self._exit_code = None
            self._started_at = time.time()
            self._ended_at = None
            self._label = label

        cmd = ["bash", str(script), *args]

        # Inherit env so HOME / PATH / SSH_AUTH_SOCK reach the script.
        env = os.environ.copy()

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                # New session so the script's own children survive if FastAPI
                # is restarted out from under it by the script's final step.
                start_new_session=True,
            )
        except OSError as exc:
            with self._lock:
                self._status = "error"
                self._exit_code = -1
                self._ended_at = time.time()
                self._lines.append(f"ERROR: failed to spawn deploy script: {exc}")
            raise

        self._proc = proc
        self._thread = threading.Thread(
            target=self._pump, args=(proc,), daemon=True
        )
        self._thread.start()
        return self.snapshot()

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                with self._lock:
                    self._lines.append(line)
            proc.wait()
            with self._lock:
                self._exit_code = proc.returncode
                self._status = "done" if proc.returncode == 0 else "error"
                self._ended_at = time.time()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._lines.append(f"ERROR: pump crashed: {exc}")
                self._status = "error"
                self._exit_code = -1
                self._ended_at = time.time()


_runner: Optional[DeployRunner] = None


def get_runner() -> DeployRunner:
    global _runner
    if _runner is None:
        _runner = DeployRunner()
    return _runner


def reset_runner() -> None:
    """Drop the cached singleton — tests use this between cases."""
    global _runner
    _runner = None
