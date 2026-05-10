from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx


class OmniVoicePersistentClient:
    def __init__(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        *,
        model: str,
        voice: str,
        response_format: str = "wav",
        speed: float = 1.0,
        language: Optional[str] = None,
    ) -> None:
        payload: dict = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
        }
        if language is not None:
            payload["language"] = language

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.api_base}/v1/audio/speech",
                    json=payload,
                )
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"OmniVoice server is not reachable at {self.api_base}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"OmniVoice server timed out at {self.api_base}: {exc}"
            ) from exc
