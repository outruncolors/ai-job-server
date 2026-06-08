"""GatewayHost — keeps live MCP client sessions and aggregates their primitives.

One :class:`ServerConn` per roster entry runs in its own asyncio task that enters
the SDK's async context managers (``stdio_client``/``streamablehttp_client`` +
``ClientSession``), performs ``initialize``, refreshes the server's
tools/resources/prompts, then parks on a shutdown event. If the session drops
(child crash, transport error) the task reconnects with capped backoff, so one
flaky server never takes down the gateway — it just reports as ``down``.

HTTP handlers call :meth:`call_tool` / :meth:`read_resource` / :meth:`get_prompt`
from other tasks; that's safe because ``ClientSession`` talks over anyio memory
streams whose receive loop runs inside the connection task.

Aggregation namespaces every primitive by server id (``<server_id>__<name>``) so
two servers exposing ``read_file`` don't collide. A lookup map avoids parsing the
separator back out (names may themselves contain ``__``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)

_MAX_BACKOFF = 30.0
_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_id(server_id: str) -> str:
    """Coerce a server id to the OpenAI tool-name charset ``[a-zA-Z0-9_-]``."""
    return _ID_RE.sub("_", server_id) or "server"


def _content_to_jsonable(result: Any) -> Any:
    """Flatten an SDK CallToolResult / read result to plain JSON.

    Prefers ``structuredContent`` when present; otherwise joins text blocks and
    surfaces non-text blocks by type so the LLM still sees *something*.
    """
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    blocks = getattr(result, "content", None)
    if blocks is None:
        # read_resource returns ``.contents``
        blocks = getattr(result, "contents", None)
    if not blocks:
        return None
    parts: list[Any] = []
    for b in blocks:
        text = getattr(b, "text", None)
        if text is not None:
            # Tool results are commonly JSON-in-text; parse when it round-trips,
            # otherwise keep the raw string (e.g. a plain file's contents).
            try:
                parts.append(json.loads(text))
            except (ValueError, TypeError):
                parts.append(text)
            continue
        # resource contents may carry blob/uri; tools may carry image/audio
        uri = getattr(b, "uri", None)
        if uri is not None:
            parts.append({"uri": str(uri), "mimeType": getattr(b, "mimeType", None)})
            continue
        parts.append({"type": getattr(b, "type", "unknown")})
    if len(parts) == 1:
        return parts[0]
    return parts


class ServerConn:
    def __init__(self, spec: dict, workspace_root: str) -> None:
        self.spec = spec
        self.id = sanitize_id(spec["id"])
        self.workspace_root = workspace_root
        self.status: str = "connecting"  # connecting | ready | down | disabled
        self.error: Optional[str] = None
        self.session: Optional[ClientSession] = None
        self.tools: list[Any] = []
        self.resources: list[Any] = []
        self.prompts: list[Any] = []
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._ready = asyncio.Event()

    def _stdio_params(self) -> StdioServerParameters:
        args = [
            a.replace("{workspace_root}", self.workspace_root)
            for a in (self.spec.get("args") or [])
        ]
        return StdioServerParameters(
            command=self.spec["command"],
            args=args,
            env={**(self.spec.get("env") or {})} or None,
        )

    async def _open_session(self):
        """Async-context that yields a started ClientSession for this transport."""
        transport = self.spec.get("transport", "stdio")
        if transport == "stdio":
            return _StdioSession(self._stdio_params())
        if transport == "http":
            return _HttpSession(self.spec["url"])
        raise ValueError(f"unknown transport: {transport!r}")

    async def _refresh(self) -> None:
        s = self.session
        assert s is not None
        try:
            self.tools = list((await s.list_tools()).tools)
        except Exception:
            self.tools = []
        try:
            self.resources = list((await s.list_resources()).resources)
        except Exception:
            self.resources = []
        try:
            self.prompts = list((await s.list_prompts()).prompts)
        except Exception:
            self.prompts = []

    async def run(self) -> None:
        if not self.spec.get("enabled", True):
            self.status = "disabled"
            return
        backoff = 1.0
        while not self._shutdown.is_set():
            self.status = "connecting"
            self.error = None
            try:
                holder = await self._open_session()
                async with holder as session:
                    self.session = session
                    await session.initialize()
                    await self._refresh()
                    self.status = "ready"
                    self._ready.set()
                    backoff = 1.0
                    await self._shutdown.wait()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — degrade, never crash the host
                self.status = "down"
                self.error = str(exc) or type(exc).__name__
                log.warning("MCP server %r down: %s", self.id, self.error)
            finally:
                self.session = None
                self._ready.clear()
            if self._shutdown.is_set():
                break
            await asyncio.sleep(min(backoff, _MAX_BACKOFF))
            backoff *= 2
        self.status = "down"

    def start(self) -> None:
        self._shutdown.clear()
        self._task = asyncio.create_task(self.run(), name=f"mcp-conn-{self.id}")

    async def stop(self) -> None:
        # Graceful first: setting the event lets ``run()`` fall out of
        # ``await self._shutdown.wait()`` and unwind the ``async with`` blocks in
        # the *same* task that entered them — anyio requires that. Cancelling mid
        # ``initialize``/backoff is the last-resort fallback.
        self._shutdown.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self.session = None
        self.status = "down"

    async def wait_ready(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


class _StdioSession:
    """Compose stdio_client + ClientSession into one async context manager."""

    def __init__(self, params: StdioServerParameters) -> None:
        self._params = params
        self._cm = None
        self._session_cm = None

    async def __aenter__(self) -> ClientSession:
        self._cm = stdio_client(self._params)
        read, write = await self._cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        return await self._session_cm.__aenter__()

    async def __aexit__(self, *exc) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(*exc)
        if self._cm is not None:
            await self._cm.__aexit__(*exc)


class _HttpSession:
    def __init__(self, url: str) -> None:
        self._url = url
        self._cm = None
        self._session_cm = None

    async def __aenter__(self) -> ClientSession:
        from mcp.client.streamable_http import streamablehttp_client

        self._cm = streamablehttp_client(self._url)
        read, write, _ = await self._cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        return await self._session_cm.__aenter__()

    async def __aexit__(self, *exc) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(*exc)
        if self._cm is not None:
            await self._cm.__aexit__(*exc)


class GatewayHost:
    def __init__(self, servers: list[dict], workspace_root: str) -> None:
        self._conns: dict[str, ServerConn] = {}
        self._workspace_root = workspace_root
        for spec in servers:
            conn = ServerConn(spec, workspace_root)
            self._conns[conn.id] = conn
        # namespaced_name -> (server_id, original_name)
        self._tool_index: dict[str, tuple[str, str]] = {}
        self._prompt_index: dict[str, tuple[str, str]] = {}
        # namespaced uri -> (server_id, original_uri)
        self._resource_index: dict[str, tuple[str, str]] = {}

    async def start_all(self, ready_timeout: float = 20.0) -> None:
        for conn in self._conns.values():
            conn.start()
        # Give servers a moment to initialize so the first /tools is populated.
        await asyncio.gather(
            *(c.wait_ready(ready_timeout) for c in self._conns.values()),
            return_exceptions=True,
        )

    async def stop_all(self) -> None:
        await asyncio.gather(
            *(c.stop() for c in self._conns.values()), return_exceptions=True
        )

    async def reconnect(self, server_id: str) -> bool:
        conn = self._conns.get(sanitize_id(server_id))
        if conn is None:
            return False
        await conn.stop()
        conn.start()
        await conn.wait_ready(20.0)
        return True

    # ---- aggregation -------------------------------------------------------

    def list_tools(self) -> list[dict]:
        out: list[dict] = []
        self._tool_index.clear()
        for conn in self._conns.values():
            for tool in conn.tools:
                ns = f"{conn.id}__{tool.name}"
                self._tool_index[ns] = (conn.id, tool.name)
                out.append(
                    {
                        "name": ns,
                        "server": conn.id,
                        "original_name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema or {"type": "object"},
                    }
                )
        return out

    def list_resources(self) -> list[dict]:
        out: list[dict] = []
        self._resource_index.clear()
        for conn in self._conns.values():
            for res in conn.resources:
                uri = str(res.uri)
                ns = f"{conn.id}__{uri}"
                self._resource_index[ns] = (conn.id, uri)
                out.append(
                    {
                        "uri": ns,
                        "server": conn.id,
                        "original_uri": uri,
                        "name": res.name or "",
                        "description": res.description or "",
                        "mimeType": res.mimeType,
                    }
                )
        return out

    def list_prompts(self) -> list[dict]:
        out: list[dict] = []
        self._prompt_index.clear()
        for conn in self._conns.values():
            for p in conn.prompts:
                ns = f"{conn.id}__{p.name}"
                self._prompt_index[ns] = (conn.id, p.name)
                out.append(
                    {
                        "name": ns,
                        "server": conn.id,
                        "original_name": p.name,
                        "description": p.description or "",
                        "arguments": [a.model_dump() for a in (p.arguments or [])],
                    }
                )
        return out

    def status(self) -> dict:
        # Refresh indexes so lookups below resolve freshly-discovered primitives.
        self.list_tools()
        self.list_resources()
        self.list_prompts()
        return {
            "servers": [
                {
                    "id": c.id,
                    "transport": c.spec.get("transport", "stdio"),
                    "status": c.status,
                    "error": c.error,
                    "tools": len(c.tools),
                    "resources": len(c.resources),
                    "prompts": len(c.prompts),
                }
                for c in self._conns.values()
            ]
        }

    # ---- call / read / get -------------------------------------------------

    def _resolve(self, index: dict, key: str) -> tuple[ServerConn, str]:
        if not index:
            # Populate on demand (first call before any list_*).
            self.list_tools()
            self.list_resources()
            self.list_prompts()
        entry = index.get(key)
        if entry is None:
            raise KeyError(key)
        conn = self._conns.get(entry[0])
        if conn is None or conn.session is None:
            raise RuntimeError(f"server {entry[0]!r} not connected")
        return conn, entry[1]

    async def call_tool(self, name: str, arguments: dict) -> Any:
        conn, original = self._resolve(self._tool_index, name)
        result = await conn.session.call_tool(original, arguments or {})
        if getattr(result, "isError", False):
            raise RuntimeError(str(_content_to_jsonable(result)))
        return _content_to_jsonable(result)

    async def read_resource(self, uri: str) -> Any:
        conn, original = self._resolve(self._resource_index, uri)
        result = await conn.session.read_resource(original)
        return _content_to_jsonable(result)

    async def get_prompt(self, name: str, arguments: dict) -> Any:
        conn, original = self._resolve(self._prompt_index, name)
        result = await conn.session.get_prompt(original, arguments or {})
        return {
            "description": getattr(result, "description", None),
            "messages": [m.model_dump() for m in getattr(result, "messages", [])],
        }
