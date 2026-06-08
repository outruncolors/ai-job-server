"""First-party stdio MCP server exposing the 6 legacy builtin tools.

This is the migration target from A6: the bespoke in-process tools
(``random_integer``, ``generate_name``, …) re-exposed over *real* MCP so there is
one path. The gateway connects to it as the ``builtins`` roster entry. The actual
tool logic is unchanged — we delegate to the existing registry + executor.

Run as ``python -m app.mcp.builtins_server`` (stdio transport).
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .executor import execute
from .models import ToolCallError
from .registry import list_tools as legacy_list_tools

server: Server = Server("ai-job-server-builtins")


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=td.name,
            description=td.description,
            inputSchema=td.input_schema.model_dump(),
        )
        for td in legacy_list_tools()
    ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    result = await execute(name, arguments or {})
    if isinstance(result, ToolCallError):
        payload = {"error": result.error, "validation_status": result.validation_status}
    else:
        payload = result.result
    return [types.TextContent(type="text", text=json.dumps(payload))]


async def _amain() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
