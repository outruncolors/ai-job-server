"""Server-side model downloader for ComfyUI.

Fetches a URL straight onto the host running this FastAPI server so SSH
users don't trigger browser-side saves on the wrong machine. Lands files
under the configured ``models_root``. v1: public URLs only.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from .config import get_config

CHUNK_SIZE = 1 << 20  # 1 MiB


class DownloadError(Exception):
    """Raised by start() for caller-facing validation problems (bad path, exists)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class DownloadState:
    id: str
    url: str
    path: str  # relative path under models_root, what the user typed
    dest_abs: Path
    status: str = "running"  # running | done | error | cancelled
    bytes_done: int = 0
    bytes_total: Optional[int] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "path": self.path,
            "status": self.status,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


def _normalize_rel_path(raw: str) -> str:
    """Trim whitespace, strip leading ``models/`` if the user typed it."""
    p = (raw or "").strip()
    if not p:
        raise DownloadError(422, "path is required")
    # Be defensive: the UI shows ``models/`` as a fixed prefix, but accept it.
    if p.startswith("models/"):
        p = p[len("models/"):]
    if p.startswith("/"):
        raise DownloadError(422, "path must be relative (no leading slash)")
    if p.endswith("/"):
        raise DownloadError(422, "path must include a filename")
    if ".." in Path(p).parts:
        raise DownloadError(422, "path may not contain '..'")
    return p


def _resolve_dest(models_root: str, rel_path: str) -> Path:
    root = Path(models_root).resolve()
    dest = (root / rel_path).resolve()
    try:
        dest.relative_to(root)
    except ValueError:
        raise DownloadError(422, "path escapes models_root")
    if dest == root:
        raise DownloadError(422, "path must include a filename")
    return dest


class ModelDownloader:
    def __init__(self) -> None:
        self._states: dict[str, DownloadState] = {}
        self._log: deque[str] = deque(maxlen=200)

    def _logline(self, msg: str) -> None:
        self._log.append(f"{time.strftime('%H:%M:%S')} {msg}")

    def start(
        self,
        url: str,
        path: str,
        overwrite: bool = False,
        authorization: Optional[str] = None,
    ) -> DownloadState:
        url = (url or "").strip()
        if not url:
            raise DownloadError(422, "url is required")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise DownloadError(422, "url must be http:// or https://")

        rel = _normalize_rel_path(path)
        cfg = get_config()
        dest_abs = _resolve_dest(cfg.models_root, rel)

        if dest_abs.exists() and not overwrite:
            raise DownloadError(409, f"destination already exists: models/{rel}")

        dest_abs.parent.mkdir(parents=True, exist_ok=True)

        auth = (authorization or "").strip() or None
        # Accept a bare token (e.g. "hf_xxx") by auto-wrapping with "Bearer ".
        if auth and not auth.lower().startswith(("bearer ", "basic ", "token ")):
            auth = f"Bearer {auth}"

        state = DownloadState(
            id=uuid.uuid4().hex[:12],
            url=url,
            path=rel,
            dest_abs=dest_abs,
        )
        # Token is held on the task closure, never written back to the public state dict.
        state.task = asyncio.create_task(self._run(state, auth))
        self._states[state.id] = state
        self._logline(f"start {state.id} {rel} ← {url}" + (" [auth]" if auth else ""))
        return state

    async def _run(self, state: DownloadState, authorization: Optional[str] = None) -> None:
        partial = state.dest_abs.with_name(state.dest_abs.name + ".partial")
        try:
            # Wipe a stale partial from a previous failed run.
            if partial.exists():
                partial.unlink()
            timeout = httpx.Timeout(connect=30.0, read=None, write=None, pool=None)
            headers = {"Authorization": authorization} if authorization else None
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", state.url, headers=headers) as r:
                    if r.status_code >= 400:
                        raise RuntimeError(f"HTTP {r.status_code} from upstream")
                    total_hdr = r.headers.get("content-length")
                    if total_hdr and total_hdr.isdigit():
                        state.bytes_total = int(total_hdr)
                    with partial.open("wb") as fh:
                        async for chunk in r.aiter_bytes(CHUNK_SIZE):
                            fh.write(chunk)
                            state.bytes_done += len(chunk)
            os.replace(partial, state.dest_abs)
            state.status = "done"
            state.finished_at = time.time()
            self._logline(f"done  {state.id} {state.path} ({state.bytes_done} bytes)")
        except asyncio.CancelledError:
            state.status = "cancelled"
            state.finished_at = time.time()
            self._logline(f"cancelled {state.id}")
            try:
                if partial.exists():
                    partial.unlink()
            except OSError:
                pass
            raise
        except Exception as exc:
            state.status = "error"
            state.error = str(exc)
            state.finished_at = time.time()
            self._logline(f"error {state.id}: {exc}")
            try:
                if partial.exists():
                    partial.unlink()
            except OSError:
                pass

    def get(self, download_id: str) -> Optional[DownloadState]:
        return self._states.get(download_id)

    def list_all(self) -> list[DownloadState]:
        return sorted(
            self._states.values(),
            key=lambda s: s.started_at,
            reverse=True,
        )

    async def cancel(self, download_id: str) -> bool:
        state = self._states.get(download_id)
        if state is None:
            return False
        if state.status != "running" or state.task is None:
            return False
        state.task.cancel()
        try:
            await state.task
        except (asyncio.CancelledError, Exception):
            pass
        return True

    def get_logs(self, tail: int = 50) -> list[str]:
        lines = list(self._log)
        if tail and tail > 0:
            return lines[-tail:]
        return lines


_downloader: Optional[ModelDownloader] = None


def get_downloader() -> ModelDownloader:
    global _downloader
    if _downloader is None:
        _downloader = ModelDownloader()
    return _downloader


def reset_downloader() -> None:
    """Drop the cached singleton — tests use this between cases."""
    global _downloader
    _downloader = None
