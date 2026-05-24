from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx


class ComfyUIClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    async def system_stats(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.base}/system_stats")
            r.raise_for_status()
            return r.json()

    async def queue(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.base}/queue")
            r.raise_for_status()
            return r.json()

    async def submit(self, workflow: dict, client_id: str) -> dict:
        payload = {"prompt": workflow, "client_id": client_id}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.base}/prompt", json=payload)
            r.raise_for_status()
            return r.json()

    async def history(self, prompt_id: Optional[str] = None) -> dict:
        url = f"{self.base}/history"
        if prompt_id:
            url += f"/{prompt_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.json()

    async def interrupt(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as c:
            await c.post(f"{self.base}/interrupt")

    async def free(self, unload_models: bool = False, free_memory: bool = True) -> None:
        async with httpx.AsyncClient(timeout=10.0) as c:
            await c.post(
                f"{self.base}/free",
                json={"unload_models": unload_models, "free_memory": free_memory},
            )

    async def fetch_view(self, filename: str, subfolder: str = "", type_: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": type_}
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(f"{self.base}/view", params=params)
            r.raise_for_status()
            return r.content

    async def upload_image(
        self, path: Path, *, content_type: str = "image/png", filename: Optional[str] = None
    ) -> dict:
        send_name = filename or path.name
        async with httpx.AsyncClient(timeout=60.0) as c:
            with path.open("rb") as f:
                r = await c.post(
                    f"{self.base}/upload/image",
                    files={"image": (send_name, f, content_type)},
                )
            r.raise_for_status()
            return r.json()

    async def object_info(self, node_class: Optional[str] = None) -> dict:
        url = f"{self.base}/object_info"
        if node_class:
            url += f"/{node_class}"
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.json()
