from __future__ import annotations

import time
from typing import Optional

import httpx

from .models import ChainLLMConfig, ChainStep


class LLMSwapError(RuntimeError):
    """Raised when the per-step ensure-loaded call fails or the preset can't be resolved."""


def resolve_preset_name(step: ChainStep) -> Optional[str]:
    """Return the preset to load for this step, or None if no swap should happen.

    Order: explicit step.preset → llamacpp.json default_preset → None (legacy mode).
    """
    if step.preset:
        return step.preset
    from ..llamacpp.config import get_config as llamacpp_get_config
    default = llamacpp_get_config().default_preset
    return default or None


def resolve_llm_peer_base() -> str:
    """Return the base URL of the node hosting the 'llm' capability."""
    from ..llamacpp.config import get_config as llamacpp_get_config
    from ..server import find_peer_for_capability, get_local_capabilities

    if "llm" in get_local_capabilities():
        port = llamacpp_get_config().port
        return f"http://127.0.0.1:{port}"
    peer = find_peer_for_capability("llm")
    if peer is None:
        raise LLMSwapError(
            "No node with 'llm' capability available (neither local nor any configured peer)"
        )
    return f"http://{peer.host}:{peer.port}"


async def ensure_loaded_for_step(
    step: ChainStep,
    base_llm: ChainLLMConfig,
    prev_preset: Optional[str],
) -> tuple[ChainLLMConfig, Optional[str], Optional[str]]:
    """Swap llama.cpp to the step's preset, then return overridden llm config + log line.

    Returns:
        (effective_llm_config, current_preset_name, log_line)
        log_line is None when the swap is skipped (legacy mode: no preset configured anywhere).
    Raises:
        LLMSwapError on resolution failure, HTTP error, or timeout.
    """
    preset_name = resolve_preset_name(step)
    if preset_name is None:
        # Legacy / single-machine mode: no preset selected and no default configured.
        # Skip ensure-loaded and use the caller's request.llm verbatim.
        return base_llm, prev_preset, None
    base_url = resolve_llm_peer_base()

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=200.0) as client:
            r = await client.post(
                f"{base_url}/v1/llamacpp/ensure-loaded",
                json={"preset": preset_name},
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise LLMSwapError(
            f"ensure-loaded for preset {preset_name!r} at {base_url} failed: {exc}"
        ) from exc

    elapsed = time.monotonic() - started

    if r.status_code >= 400:
        raise LLMSwapError(
            f"ensure-loaded for preset {preset_name!r} returned {r.status_code}: {r.text}"
        )

    try:
        result = r.json()
    except ValueError as exc:
        raise LLMSwapError(
            f"ensure-loaded for preset {preset_name!r} returned non-JSON body: {exc}"
        ) from exc

    swapped = bool(result.get("swapped")) or elapsed > 2.0
    if swapped:
        prev_label = prev_preset or "(none)"
        log_line = f"LLM swap: {prev_label} → {preset_name} (loaded in {elapsed:.1f}s)"
    else:
        log_line = f"LLM already loaded: {preset_name}"

    new_llm = base_llm.model_copy(update={
        "api_base": f"{base_url}/v1",
        "model": preset_name,
    })
    return new_llm, preset_name, log_line
