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


def _boost_multimodal_args(args: Optional[dict], *, min_ctx: int) -> dict:
    """Copy of preset ``args`` with ``ctx_size`` raised to at least ``min_ctx``
    (never lowering a larger value) and any output-length cap removed.

    Image embeddings consume a large share of context, so a small preset
    ``ctx_size`` truncates long Vision descriptions / STT transcripts
    (``finish_reason=length``). Deterministic — same input → same output — so the
    swap hash stays stable and the model isn't needlessly reloaded between calls.
    """
    out = dict(args or {})
    try:
        current = int(out.get("ctx_size") or 0)
    except (TypeError, ValueError):
        current = 0
    out["ctx_size"] = max(current, int(min_ctx))
    for cap_key in ("n_predict", "n-predict", "predict"):
        out.pop(cap_key, None)
    return out


async def _multimodal_ensure_body(api_base: str, preset_name: str, min_ctx: int) -> dict:
    """ensure-loaded body for the multimodal preset: the stored preset with
    boosted args (inline), or — if it can't be fetched — just the name, so the
    feature still works (without the ctx bump) when the preset store is unreachable.
    """
    if min_ctx <= 0:
        return {"preset": preset_name}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{api_base}/v1/llm-presets/{preset_name}")
        if r.status_code < 400:
            preset = r.json()
            if isinstance(preset, dict) and preset.get("model_path"):
                preset["args"] = _boost_multimodal_args(preset.get("args"), min_ctx=min_ctx)
                return {"preset": preset}
    except (httpx.ConnectError, httpx.TimeoutException, ValueError):
        pass
    return {"preset": preset_name}


async def ensure_multimodal_loaded(
    *,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout_seconds: int = 300,
) -> ChainLLMConfig:
    """Swap the llm node to the multimodal preset and return a chat config for it.

    Mirrors :func:`app.chain.llm_swap.ensure_loaded_for_step` but for the
    standalone Vision/STT endpoints (no chain step involved). The preset is loaded
    with a guaranteed-large ``ctx_size`` (see :func:`_boost_multimodal_args`) so
    long descriptions/transcripts aren't truncated. Raises :class:`LLMSwapError`
    when no llm node is reachable or the swap fails.
    """
    from ..llamacpp.config import get_config as llamacpp_get_config

    preset_name = resolve_multimodal_preset()
    api_base = resolve_llm_peer_api_base()
    min_ctx = max(0, int(llamacpp_get_config().multimodal_min_ctx or 0))
    ensure_body = await _multimodal_ensure_body(api_base, preset_name, min_ctx)

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=float(timeout_seconds)) as client:
            r = await client.post(
                f"{api_base}/v1/llamacpp/ensure-loaded",
                json=ensure_body,
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
