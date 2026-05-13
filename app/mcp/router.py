from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .executor import execute
from .models import ToolCallError, ToolCallRequest, ToolCallResult
from .registry import get_tool, list_tools

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


@router.get("/tools")
async def get_tools():
    return {"tools": list_tools()}


@router.post("/tools/{name}/call")
async def call_tool(name: str, req: ToolCallRequest) -> ToolCallResult | ToolCallError:
    if get_tool(name) is None:
        raise HTTPException(status_code=404, detail=f"Tool not found: {name}")
    return await execute(name, req.arguments)
