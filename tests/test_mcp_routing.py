"""Phase 0 — MCP executor routing, registry merge, client resolution, routes.

Unit-level: no real gateway process. The gateway client is monkeypatched so we
test the *routing* decisions (legacy in-process vs gateway) and capability gating
in isolation.
"""

from __future__ import annotations

import json

import pytest

import app.mcp.client as client
import app.mcp.executor as executor
import app.mcp.registry as registry
from app.mcp.models import ToolCallError, ToolCallResult


def _write_server_config(tmp_path, payload):
    import app.server as s

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "server.json").write_text(json.dumps(payload), encoding="utf-8")
    s.reset_server_config()


# ---- executor routing ------------------------------------------------------


async def test_executor_runs_legacy_builtin_in_process(monkeypatch):
    called = {}

    async def _fail(*a, **k):
        called["gateway"] = True
        return {"ok": False, "error": "should not be called"}

    monkeypatch.setattr(executor, "mcp_call_tool", _fail, raising=False)
    # random_integer is a legacy builtin → never touches the gateway
    res = await executor.execute("random_integer", {"min": 5, "max": 5})
    assert isinstance(res, ToolCallResult)
    assert res.result == {"value": 5}
    assert "gateway" not in called


async def test_executor_routes_unknown_to_gateway(monkeypatch):
    async def _gw(name, args):
        assert name == "fs__read_file"
        return {"ok": True, "result": {"text": "hello"}}

    monkeypatch.setattr(client, "mcp_call_tool", _gw)
    res = await executor.execute("fs__read_file", {"path": "/x"})
    assert isinstance(res, ToolCallResult)
    assert res.result == {"text": "hello"}


async def test_executor_gateway_error_becomes_toolcallerror(monkeypatch):
    async def _gw(name, args):
        return {"ok": False, "error": "tool not found: zzz"}

    monkeypatch.setattr(client, "mcp_call_tool", _gw)
    res = await executor.execute("zzz", {})
    assert isinstance(res, ToolCallError)
    assert res.validation_status == "unknown_tool"


async def test_executor_validates_legacy_args(monkeypatch):
    res = await executor.execute("random_integer", {"min": "bad"})
    assert isinstance(res, ToolCallError)
    assert res.validation_status == "invalid"


# ---- registry merge --------------------------------------------------------


async def test_openai_tools_for_merges_builtins_and_gateway(monkeypatch):
    async def _list():
        return [
            {
                "name": "fs__read_file",
                "description": "read a file",
                "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
            }
        ]

    monkeypatch.setattr(client, "mcp_list_tools", _list)
    tools = await registry.openai_tools_for(["random_integer", "fs__read_file"])
    names = {t["function"]["name"] for t in tools}
    assert names == {"random_integer", "fs__read_file"}
    fs = next(t for t in tools if t["function"]["name"] == "fs__read_file")
    assert fs["function"]["parameters"]["properties"]["path"]["type"] == "string"


async def test_openai_tools_for_skips_missing(monkeypatch):
    async def _list():
        return []

    monkeypatch.setattr(client, "mcp_list_tools", _list)
    tools = await registry.openai_tools_for(["random_integer", "ghost_tool"])
    names = {t["function"]["name"] for t in tools}
    assert names == {"random_integer"}


async def test_openai_tools_for_builtins_only_skips_gateway(monkeypatch):
    hit = {}

    async def _list():
        hit["called"] = True
        return []

    monkeypatch.setattr(client, "mcp_list_tools", _list)
    tools = await registry.openai_tools_for(["random_integer"])
    assert len(tools) == 1
    assert "called" not in hit  # no gateway round-trip when all names are builtins


# ---- client peer resolution ------------------------------------------------


def test_resolve_peer_local(tmp_path):
    _write_server_config(tmp_path, {"capabilities": ["web", "mcp"], "peers": []})
    assert client.has_local_mcp() is True
    assert client.resolve_mcp_peer_api_base() == "http://127.0.0.1:8090"


def test_resolve_peer_remote(tmp_path):
    _write_server_config(
        tmp_path,
        {
            "capabilities": ["web"],
            "peers": [{"name": "g", "host": "gpu.local", "port": 8090, "capabilities": ["mcp"]}],
        },
    )
    assert client.has_local_mcp() is False
    assert client.resolve_mcp_peer_api_base() == "http://gpu.local:8090"


def test_resolve_peer_none(tmp_path):
    _write_server_config(tmp_path, {"capabilities": ["web"], "peers": []})
    with pytest.raises(client.MCPUnavailable):
        client.resolve_mcp_peer_api_base()


# ---- routes: capability gating + back-compat call -------------------------


def test_control_routes_gated_without_mcp(client_fixture, tmp_path):
    _write_server_config(tmp_path, {"capabilities": ["web"], "peers": []})
    r = client_fixture.get("/v1/mcp/status")
    assert r.status_code == 503
    assert r.json()["detail"]["needed"] == "mcp"


def test_call_route_runs_builtin_regardless_of_capability(client_fixture, tmp_path):
    # Data routes are not gated; a legacy builtin runs in-process even with no mcp.
    _write_server_config(tmp_path, {"capabilities": ["web"], "peers": []})
    r = client_fixture.post(
        "/v1/mcp/tools/random_integer/call", json={"arguments": {"min": 8, "max": 8}}
    )
    assert r.status_code == 200
    assert r.json()["result"] == {"value": 8}


def test_status_route_with_mcp_but_gateway_down(client_fixture, tmp_path, monkeypatch):
    _write_server_config(tmp_path, {"capabilities": ["web", "mcp"], "peers": []})
    # point gateway at a dead port so health is False
    import app.mcp.config as cfg

    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "mcp.json")
    cfg.reset_config()
    cfg.save_config(cfg.MCPConfig(port=59999))
    r = client_fixture.get("/v1/mcp/status")
    assert r.status_code == 200
    assert r.json()["running"] is False


@pytest.fixture()
def client_fixture():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
