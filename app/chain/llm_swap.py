from __future__ import annotations

import time
from typing import Optional

import httpx

from .models import Alternative, ChainLLMConfig, ChainStep


class LLMSwapError(RuntimeError):
    """Raised when the per-step ensure-loaded call fails or the preset can't be resolved."""


def resolve_preset_name(alt: Alternative) -> Optional[str]:
    """Return the preset to load for this alternative, or None if no swap should happen.

    Order: explicit alt.preset → llamacpp.json default_preset → None (legacy mode).
    """
    if alt.preset:
        return alt.preset
    from ..llamacpp.config import get_config as llamacpp_get_config
    default = llamacpp_get_config().default_preset
    return default or None


def resolve_llm_peer_api_base() -> str:
    """Base URL of the ai-job-server FastAPI on the LLM-capable node.

    Used to call /v1/llamacpp/ensure-loaded and /v1/llamacpp/config. This is
    the *control plane* — port 8090 by convention.
    """
    from ..llamacpp.config import get_config as llamacpp_get_config
    from ..server import find_peer_for_capability, get_local_capabilities

    if "llm" in get_local_capabilities():
        # Local FastAPI is on whatever port uvicorn is listening on; for the
        # local case we can short-circuit and talk to llama-server directly
        # (see resolve_llm_server_url), so this URL is only used to call the
        # local /v1/llamacpp/ensure-loaded — same FastAPI we're already inside.
        return "http://127.0.0.1:8090"
    peer = find_peer_for_capability("llm")
    if peer is None:
        raise LLMSwapError(
            "No node with 'llm' capability available (neither local nor any configured peer)"
        )
    return f"http://{peer.host}:{peer.port}"


async def resolve_llm_server_url(api_base: str) -> str:
    """Base URL of the llama-server process on the LLM-capable node.

    This is the *data plane* — where /v1/chat/completions lives, typically
    port 8080. Fetched from /v1/llamacpp/config on the peer because the
    llama-server port and host are configurable per-node and aren't carried
    in config/server.json (which only knows about the FastAPI control port).
    """
    from ..llamacpp.config import get_config as llamacpp_get_config
    from ..server import find_peer_for_capability, get_local_capabilities

    if "llm" in get_local_capabilities():
        cfg = llamacpp_get_config()
        return f"http://127.0.0.1:{cfg.port}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{api_base}/v1/llamacpp/config")
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise LLMSwapError(
            f"could not fetch llama-server config from {api_base}: {exc}"
        ) from exc
    if r.status_code >= 400:
        raise LLMSwapError(
            f"GET {api_base}/v1/llamacpp/config returned {r.status_code}: {r.text}"
        )
    try:
        cfg = r.json()
    except ValueError as exc:
        raise LLMSwapError(
            f"non-JSON body from {api_base}/v1/llamacpp/config: {exc}"
        ) from exc
    peer = find_peer_for_capability("llm")
    host = peer.host if peer else "127.0.0.1"
    port = int(cfg.get("port") or 8080)
    return f"http://{host}:{port}"


async def ensure_loaded_for_step(
    step: ChainStep,
    alt: Alternative,
    base_llm: ChainLLMConfig,
    prev_preset: Optional[str],
) -> tuple[ChainLLMConfig, Optional[str], Optional[str]]:
    """Swap llama.cpp to the chosen alternative's preset, then return overridden llm config + log line.

    Returns:
        (effective_llm_config, current_preset_name, log_line)
        log_line is None when the swap is skipped (legacy mode: no preset configured anywhere).
    Raises:
        LLMSwapError on resolution failure, HTTP error, or timeout.
    """
    preset_name = resolve_preset_name(alt)
    if preset_name is None:
        # Legacy / single-machine mode: no preset selected and no default configured.
        # Skip ensure-loaded and use the caller's request.llm verbatim.
        return base_llm, prev_preset, None
    api_base = resolve_llm_peer_api_base()

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=200.0) as client:
            r = await client.post(
                f"{api_base}/v1/llamacpp/ensure-loaded",
                json={"preset": preset_name},
            )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise LLMSwapError(
            f"ensure-loaded for preset {preset_name!r} at {api_base} failed: {exc}"
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

    llama_url = await resolve_llm_server_url(api_base)
    new_llm = base_llm.model_copy(update={
        "api_base": f"{llama_url}/v1",
        "model": preset_name,
    })
    return new_llm, preset_name, log_line
