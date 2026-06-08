"""Phase 0 — MCP gateway host + manager integration tests.

These exercise the *real* MCP protocol path: the GatewayHost connects (over stdio,
via the official SDK) to the first-party builtins MCP server, performs the
initialize handshake, aggregates + namespaces tools, and round-trips a tool call.
The manager test launches the actual gateway process and adopts/stops it.
"""

from __future__ import annotations

import socket
import sys

import httpx
import pytest

from app.mcp.gateway.host import GatewayHost, sanitize_id

BUILTINS_ROSTER = [
    {
        "id": "builtins",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.mcp.builtins_server"],
        "env": {},
    }
]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_sanitize_id():
    assert sanitize_id("fs") == "fs"
    assert sanitize_id("my.server") == "my_server"
    assert sanitize_id("a b/c") == "a_b_c"
    assert sanitize_id("") == "server"


async def test_host_connects_and_aggregates():
    host = GatewayHost(BUILTINS_ROSTER, workspace_root="/tmp")
    await host.start_all(ready_timeout=20)
    try:
        status = host.status()
        srv = status["servers"][0]
        assert srv["status"] == "ready"
        assert srv["tools"] == 6  # the 6 legacy builtins

        tools = host.list_tools()
        names = {t["name"] for t in tools}
        # namespaced by server id
        assert "builtins__random_integer" in names
        assert all(t["name"].startswith("builtins__") for t in tools)
        # input schema preserved as JSON Schema
        ri = next(t for t in tools if t["name"] == "builtins__random_integer")
        assert ri["input_schema"]["type"] == "object"
        assert "min" in ri["input_schema"]["properties"]
    finally:
        await host.stop_all()


async def test_host_tool_call_roundtrip():
    host = GatewayHost(BUILTINS_ROSTER, workspace_root="/tmp")
    await host.start_all(ready_timeout=20)
    try:
        res = await host.call_tool("builtins__random_integer", {"min": 42, "max": 42})
        assert res == {"value": 42}
        name = await host.call_tool("builtins__generate_name", {"gender": "male"})
        assert isinstance(name["name"], str) and name["name"]
    finally:
        await host.stop_all()


async def test_host_unknown_tool_raises():
    host = GatewayHost(BUILTINS_ROSTER, workspace_root="/tmp")
    await host.start_all(ready_timeout=20)
    try:
        with pytest.raises(KeyError):
            await host.call_tool("builtins__nope", {})
    finally:
        await host.stop_all()


async def test_host_reconnect():
    host = GatewayHost(BUILTINS_ROSTER, workspace_root="/tmp")
    await host.start_all(ready_timeout=20)
    try:
        assert await host.reconnect("builtins") is True
        assert host.status()["servers"][0]["status"] == "ready"
        res = await host.call_tool("builtins__random_integer", {"min": 1, "max": 1})
        assert res == {"value": 1}
        assert await host.reconnect("does-not-exist") is False
    finally:
        await host.stop_all()


async def test_host_bad_server_degrades_without_crashing():
    roster = [
        {"id": "broken", "transport": "stdio", "command": "/nonexistent/bin", "args": []},
        *BUILTINS_ROSTER,
    ]
    host = GatewayHost(roster, workspace_root="/tmp")
    await host.start_all(ready_timeout=8)
    try:
        statuses = {s["id"]: s["status"] for s in host.status()["servers"]}
        assert statuses["builtins"] == "ready"
        assert statuses["broken"] in ("down", "connecting")
        # the healthy server still works
        assert await host.call_tool("builtins__random_integer", {"min": 3, "max": 3}) == {
            "value": 3
        }
    finally:
        await host.stop_all()


async def test_manager_adopt_start_stop(tmp_path, monkeypatch):
    import app.mcp.config as cfg
    import app.mcp.manager as mgr_mod

    port = _free_port()
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "mcp.json")
    monkeypatch.setattr(cfg, "SERVERS_PATH", tmp_path / "mcp_servers.json")
    cfg.reset_config()
    cfg.save_config(cfg.MCPConfig(port=port, workspace_root=str(tmp_path)))
    cfg.save_servers(cfg.MCPServersConfig(servers=[cfg.MCPServerSpec(**BUILTINS_ROSTER[0])]))
    mgr_mod.reset_manager()
    mgr = mgr_mod.get_manager()

    # nothing running yet
    assert await mgr.adopt() is False
    status = await mgr.start()
    try:
        assert status["running"] is True
        assert status["port"] == port
        # the real gateway data plane is up and aggregating the builtins
        async with httpx.AsyncClient() as c:
            r = await c.get(f"http://127.0.0.1:{port}/tools", timeout=10)
        tools = r.json()["tools"]
        assert any(t["name"] == "builtins__random_integer" for t in tools)
        # a fresh manager can adopt the running process
        mgr_mod.reset_manager()
        assert await mgr_mod.get_manager().adopt() is True
    finally:
        await mgr_mod.get_manager().stop()
    assert (await mgr_mod.get_manager().status())["running"] is False
    mgr_mod.reset_manager()
