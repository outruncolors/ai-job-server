"""Peer-forwarding MCP client — local-or-peer gateway resolution.

Mirrors ``app/chain/llm_swap.py``'s two-port model:

- **Control plane** (FastAPI, ~8090): how a node without ``mcp`` reaches one that
  has it. ``resolve_mcp_peer_api_base()`` returns the local FastAPI when this node
  is mcp-capable, else the peer's FastAPI.
- **Data plane** (gateway, ~8082): the aggregated tools/resources/prompts. When
  mcp is local we hit ``127.0.0.1:<gateway port>`` directly; otherwise we forward
  to the peer's capability-gated ``/v1/mcp/...`` control routes (which resolve
  locally on the peer). The gateway port itself stays bound to localhost for
  safety — cross-node access always goes through the gated control plane.

Every function degrades rather than raising into a chain turn: list_* return ``[]``
and call/read/get return ``{"ok": False, "error": ...}`` when no gateway is
reachable, so a chain that merely *offers* MCP tools still runs without one.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from ..server import find_peer_for_capability, get_local_capabilities
from .config import get_config

log = logging.getLogger(__name__)

_TIMEOUT = 30.0


class MCPUnavailable(RuntimeError):
    pass


def has_local_mcp() -> bool:
    return "mcp" in get_local_capabilities()


def _local_gateway_base() -> str:
    cfg = get_config()
    return f"http://127.0.0.1:{cfg.port}"


def resolve_mcp_peer_api_base() -> str:
    """FastAPI control-plane base of the mcp-capable node (local or peer)."""
    if has_local_mcp():
        return "http://127.0.0.1:8090"
    peer = find_peer_for_capability("mcp")
    if peer is None:
        raise MCPUnavailable(
            "no node with 'mcp' capability available (neither local nor any peer)"
        )
    return f"http://{peer.host}:{peer.port}"


async def _get_json(url: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.get(url)
        if r.status_code >= 400:
            log.warning("MCP GET %s -> %s", url, r.status_code)
            return None
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("MCP GET %s failed: %s", url, exc)
        return None


async def _post_json(url: str, body: dict) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(url, json=body)
        if r.status_code >= 400:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text}"}
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


async def _list(kind: str) -> list[dict]:
    """kind in {tools, resources, prompts}."""
    if has_local_mcp():
        data = await _get_json(f"{_local_gateway_base()}/{kind}")
    else:
        try:
            api_base = resolve_mcp_peer_api_base()
        except MCPUnavailable:
            return []
        data = await _get_json(f"{api_base}/v1/mcp/{kind}")
    if not data:
        return []
    return data.get(kind, [])


async def mcp_list_tools() -> list[dict]:
    return await _list("tools")


async def mcp_list_resources() -> list[dict]:
    return await _list("resources")


async def mcp_list_prompts() -> list[dict]:
    return await _list("prompts")


def _normalize_call(body: Optional[dict]) -> dict:
    """Coerce either response shape into {ok, result, error}.

    The local gateway returns {"ok", "result"/"error"}; the peer control plane's
    legacy call route returns a ToolCallResult/ToolCallError envelope.
    """
    if not body:
        return {"ok": False, "error": "no response from gateway"}
    if "ok" in body:
        return body
    if "error" in body and "result" not in body:
        return {"ok": False, "error": body["error"]}
    if "result" in body:
        return {"ok": True, "result": body["result"]}
    return {"ok": False, "error": "unrecognized gateway response"}


async def mcp_call_tool(name: str, arguments: dict) -> dict:
    if has_local_mcp():
        body = await _post_json(
            f"{_local_gateway_base()}/tools/{name}/call", {"arguments": arguments or {}}
        )
        return _normalize_call(body)
    try:
        api_base = resolve_mcp_peer_api_base()
    except MCPUnavailable as exc:
        return {"ok": False, "error": str(exc)}
    body = await _post_json(
        f"{api_base}/v1/mcp/tools/{name}/call", {"arguments": arguments or {}}
    )
    return _normalize_call(body)


async def mcp_read_resource(uri: str) -> dict:
    if has_local_mcp():
        body = await _post_json(f"{_local_gateway_base()}/resources/read", {"uri": uri})
        return _normalize_call(body)
    try:
        api_base = resolve_mcp_peer_api_base()
    except MCPUnavailable as exc:
        return {"ok": False, "error": str(exc)}
    body = await _post_json(f"{api_base}/v1/mcp/resources/read", {"uri": uri})
    return _normalize_call(body)


async def mcp_get_prompt(name: str, arguments: dict) -> dict:
    if has_local_mcp():
        body = await _post_json(
            f"{_local_gateway_base()}/prompts/{name}/get", {"arguments": arguments or {}}
        )
        return _normalize_call(body)
    try:
        api_base = resolve_mcp_peer_api_base()
    except MCPUnavailable as exc:
        return {"ok": False, "error": str(exc)}
    body = await _post_json(
        f"{api_base}/v1/mcp/prompts/{name}/get", {"arguments": arguments or {}}
    )
    return _normalize_call(body)
