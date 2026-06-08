"""The MCP gateway process: a real MCP host/client built on the official `mcp` SDK.

Run as ``python -m app.mcp.gateway``. It connects to the roster of real MCP
servers (``config/mcp_servers.json``), keeps the sessions alive, aggregates their
tools/resources/prompts into one namespace, and exposes a unified HTTP data plane
(default ``:8082``). The FastAPI control plane (``/v1/mcp/...``) fronts it; the
MCPManager supervises this process exactly like llama-server / ComfyUI.
"""
