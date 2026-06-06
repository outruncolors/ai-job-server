"""Load the multimodal preset on the llm node and return a chat config for it.

Reuses the chain executor's node-resolution helpers so Vision/STT route to the
same llama-server (local or peer) that chain LLM steps use. The hash-based
``ensure-loaded`` keeps the model resident between calls; switching back to the
text model happens automatically on the next normal chain LLM step.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

from ..chain.llm_swap import (
    LLMSwapError,
    resolve_llm_peer_api_base,
    resolve_llm_server_url,
)
from ..chain.models import ChainLLMConfig


def resolve_multimodal_preset() -> str:
    """Name of the preset to load for Vision/STT, or raise if unconfigured."""
    from ..llamacpp.config import get_config as llamacpp_get_config

    preset = llamacpp_get_config().multimodal_preset
    if not preset:
        raise LLMSwapError(
            "no multimodal_preset configured in llamacpp.json — set it to the "
            "name of the Gemma 4 E4B (vision/audio) preset"
        )
    return preset


async def ensure_multimodal_loaded(
    *,
    temperature: float = 0.4,
    max_tokens: int = 1024,
    timeout_seconds: int = 300,
) -> ChainLLMConfig:
    """Swap the llm node to the multimodal preset and return a chat config for it.

    Mirrors :func:`app.chain.llm_swap.ensure_loaded_for_step` but for the
    standalone Vision/STT endpoints (no chain step involved). Raises
    :class:`LLMSwapError` when no llm node is reachable or the swap fails.
    """
    preset_name = resolve_multimodal_preset()
    api_base = resolve_llm_peer_api_base()

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=float(timeout_seconds)) as client:
            r = await client.post(
                f"{api_base}/v1/llamacpp/ensure-loaded",
                json={"preset": preset_name},
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise LLMSwapError(
            f"ensure-loaded for multimodal preset {preset_name!r} at {api_base} failed: {exc}"
        ) from exc

    if r.status_code >= 400:
        raise LLMSwapError(
            f"ensure-loaded for multimodal preset {preset_name!r} returned "
            f"{r.status_code}: {r.text}"
        )

    llama_url = await resolve_llm_server_url(api_base)
    _ = time.monotonic() - started
    return ChainLLMConfig(
        api_base=f"{llama_url}/v1",
        model=preset_name,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
