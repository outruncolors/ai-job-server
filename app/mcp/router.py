"""MCP control + data plane (``/v1/mcp/...``).

- **Control** routes (gated ``requires_capability("mcp")``) supervise the gateway
  process and edit the server roster — they only make sense on a node that hosts
  the gateway.
- **Data** routes are *not* hard route-gated: they resolve to the local-or-peer
  gateway via ``app/mcp/client.py`` so any node can list/call MCP tools even
  without the capability locally.

The legacy ``GET /v1/mcp/tools`` + ``POST /v1/mcp/tools/{name}/call`` contract is
preserved (now backed by the gateway / in-process bridge).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..server import requires_capability
from . import client
from .config import (
    MCPConfig,
    MCPServersConfig,
    get_config,
    save_config,
    save_servers,
)
from .executor import execute
from .manager import get_manager
from .models import ToolCallError, ToolCallRequest, ToolCallResult

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])

_mcp_gate = Depends(requires_capability("mcp"))


# ---- control plane (gated) ------------------------------------------------


@router.post("/start", dependencies=[_mcp_gate])
async def start_gateway():
    return await get_manager().start()


@router.post("/stop", dependencies=[_mcp_gate])
async def stop_gateway():
    return await get_manager().stop()


@router.post("/restart", dependencies=[_mcp_gate])
async def restart_gateway():
    return await get_manager().restart()


@router.get("/status", dependencies=[_mcp_gate])
async def gateway_status():
    mgr = get_manager()
    status = await mgr.status()
    servers: dict = {}
    if status.get("running"):
        data = await client._get_json(f"http://127.0.0.1:{get_config().port}/servers")
        if data:
            servers = data
    return {**status, **servers, "logs": mgr.get_logs(40)}


@router.get("/config", dependencies=[_mcp_gate])
async def get_mcp_config():
    """Gateway runtime config (carries the data-plane port for peer discovery)."""
    return get_config().model_dump()


@router.put("/config", dependencies=[_mcp_gate])
async def put_mcp_config(cfg: MCPConfig):
    save_config(cfg)
    return cfg.model_dump()


@router.get("/servers", dependencies=[_mcp_gate])
async def get_servers_roster():
    from .config import get_servers

    return get_servers().model_dump()


@router.put("/servers", dependencies=[_mcp_gate])
async def put_servers_roster(servers: MCPServersConfig):
    save_servers(servers)
    return servers.model_dump()


@router.post("/servers/{server_id}/reconnect", dependencies=[_mcp_gate])
async def reconnect_server(server_id: str):
    data = await client._post_json(
        f"http://127.0.0.1:{get_config().port}/servers/{server_id}/reconnect", {}
    )
    return data or {"reconnected": False}


# ---- data plane (peer-forwarding, not hard-gated) -------------------------


@router.get("/tools")
async def list_tools_route():
    return {"tools": await client.mcp_list_tools()}


@router.get("/resources")
async def list_resources_route():
    return {"resources": await client.mcp_list_resources()}


@router.get("/prompts")
async def list_prompts_route():
    return {"prompts": await client.mcp_list_prompts()}


@router.post("/tools/{name}/call")
async def call_tool_route(name: str, req: ToolCallRequest) -> ToolCallResult | ToolCallError:
    # Routes legacy builtins in-process and gateway tools via the client.
    return await execute(name, req.arguments)


class ReadResourceBody(BaseModel):
    uri: str


class GetPromptBody(BaseModel):
    arguments: dict = {}


@router.post("/resources/read")
async def read_resource_route(body: ReadResourceBody):
    resp = await client.mcp_read_resource(body.uri)
    if not resp.get("ok"):
        raise HTTPException(status_code=502, detail=resp.get("error", "read failed"))
    return resp


@router.post("/prompts/{name}/get")
async def get_prompt_route(name: str, body: GetPromptBody):
    resp = await client.mcp_get_prompt(name, body.arguments)
    if not resp.get("ok"):
        raise HTTPException(status_code=502, detail=resp.get("error", "get failed"))
    return resp
