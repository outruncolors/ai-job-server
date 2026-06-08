"""The gateway's HTTP data plane (default ``:8082``) + process entrypoint.

A deliberately tiny FastAPI app backed by a single :class:`GatewayHost`. The
FastAPI control plane (``app/mcp/router.py``) on ``:8090`` fronts these routes;
nothing else should talk to ``:8082`` directly except the control plane and the
peer-forwarding client.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from ..config import get_config, get_servers
from .host import GatewayHost

log = logging.getLogger(__name__)

_host: Optional[GatewayHost] = None


def get_host() -> GatewayHost:
    assert _host is not None, "gateway host not started"
    return _host


class CallToolBody(BaseModel):
    arguments: dict[str, Any] = {}


class ReadResourceBody(BaseModel):
    uri: str


class GetPromptBody(BaseModel):
    arguments: dict[str, Any] = {}


def build_app() -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        global _host
        cfg = get_config()
        roster = [s.model_dump() for s in get_servers().servers]
        _host = GatewayHost(roster, workspace_root=cfg.workspace_root)
        await _host.start_all()
        try:
            yield
        finally:
            if _host is not None:
                await _host.stop_all()
                _host = None

    app = FastAPI(title="mcp-gateway", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok", **get_host().status()}

    @app.get("/tools")
    async def tools():
        return {"tools": get_host().list_tools()}

    @app.get("/resources")
    async def resources():
        return {"resources": get_host().list_resources()}

    @app.get("/prompts")
    async def prompts():
        return {"prompts": get_host().list_prompts()}

    @app.get("/servers")
    async def servers():
        return get_host().status()

    @app.post("/servers/{server_id}/reconnect")
    async def reconnect(server_id: str):
        ok = await get_host().reconnect(server_id)
        return {"reconnected": ok}

    @app.post("/tools/{name}/call")
    async def call_tool(name: str, body: CallToolBody):
        try:
            result = await get_host().call_tool(name, body.arguments)
            return {"ok": True, "result": result}
        except KeyError:
            return {"ok": False, "error": f"tool not found: {name}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    @app.post("/resources/read")
    async def read_resource(body: ReadResourceBody):
        try:
            result = await get_host().read_resource(body.uri)
            return {"ok": True, "result": result}
        except KeyError:
            return {"ok": False, "error": f"resource not found: {body.uri}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    @app.post("/prompts/{name}/get")
    async def get_prompt(name: str, body: GetPromptBody):
        try:
            result = await get_host().get_prompt(name, body.arguments)
            return {"ok": True, "result": result}
        except KeyError:
            return {"ok": False, "error": f"prompt not found: {name}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    cfg = get_config()
    uvicorn.run(build_app(), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
