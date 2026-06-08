# MCP — Model Context Protocol

ai-job-server is a **real MCP host**. A long-lived **MCP gateway process** per machine
uses the official [`mcp`](https://pypi.org/project/mcp/) Python SDK to connect to real
MCP servers (stdio children or Streamable-HTTP endpoints), performs the `initialize`
handshake, keeps the sessions alive, and aggregates their **tools / resources / prompts**
into one namespace. The FastAPI control plane (`/v1/mcp/...`) fronts the gateway exactly
as it fronts llama-server — same supervised, multi-machine, boots-with-the-machine model.

> **History.** The old `app/mcp/` was a bespoke in-process registry of 6 Python tools
> over a plain REST API — not MCP. Those 6 builtins still work (see *Builtins bridge*),
> but everything is now a thin shell over the standardized gateway.

## Architecture — two ports

| Plane | Process | Port | What lives there |
|---|---|---|---|
| **Control** | FastAPI (`uvicorn app.main:app`) | ~8090 | `/v1/mcp/*` routes; supervises the gateway |
| **Data** | MCP gateway (`python -m app.mcp.gateway`) | ~8082 | aggregated tools/resources/prompts, `tools/call`, `resources/read`, `prompts/get`, `/health` |

Mirrors the `llm` → llama-server split: `config/server.json` peers carry the FastAPI
port; the gateway port is fetched from the peer's `/v1/mcp/config` for discovery.

## Capability + supervision

- Add `"mcp"` to a node's `capabilities` in `config/server.json`.
- `MCPManager` (`app/mcp/manager.py`) is a singleton supervised by the `app/main.py`
  lifespan: on startup `adopt() or start()`, on shutdown `stop()` (SIGTERM→SIGKILL on the
  process group). Because the existing systemd unit `scripts/systemd/ai-job-server.service`
  (`Restart=on-failure`) starts uvicorn on boot, the gateway comes up with the machine —
  **no new systemd unit required** (matches comfyui/llamacpp). An adopted gateway also
  survives a FastAPI-only restart.

## Config (both gitignored under `config/`)

- **`config/mcp.json`** — gateway runtime config (`MCPConfig`): `host`, `port` (8082),
  `autostart`, `python`, `entrypoint`, `workspace_root`.
- **`config/mcp_servers.json`** — the roster of MCP servers (`MCPServersConfig`):

  ```json
  {
    "servers": [
      { "id": "builtins", "transport": "stdio",
        "command": ".venv/bin/python", "args": ["-m", "app.mcp.builtins_server"] },
      { "id": "fs", "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{workspace_root}"] },
      { "id": "remote", "transport": "http", "url": "http://host:9000/mcp" }
    ]
  }
  ```

  `{workspace_root}` in stdio args expands to `MCPConfig.workspace_root`. Set `enabled:false`
  to keep an entry without connecting. The default roster ships only the first-party
  `builtins` server — add `fs`/`git`/etc. once `npx`/`uvx` and a workspace root are chosen.

## Routes

**Control** (gated `requires_capability("mcp")`): `POST /v1/mcp/start|stop|restart`,
`GET /v1/mcp/status`, `GET/PUT /v1/mcp/config`, `GET/PUT /v1/mcp/servers`,
`POST /v1/mcp/servers/{id}/reconnect`.

**Data** (NOT route-gated — peer-forwarding): `GET /v1/mcp/tools|resources|prompts`,
`POST /v1/mcp/tools/{name}/call`, `POST /v1/mcp/resources/read`,
`POST /v1/mcp/prompts/{name}/get`. These resolve to the **local-or-peer** gateway via
`app/mcp/client.py`, so any node can use MCP even without the capability locally.

## Multi-machine / peer-forwarding

`app/mcp/client.py` mirrors `app/chain/llm_swap.py`: if `"mcp"` is local it talks straight
to `127.0.0.1:<gateway port>`; otherwise it forwards to the peer's gated `/v1/mcp/*` routes
(which resolve locally on the peer). The gateway port itself stays bound to localhost — all
cross-node access goes through the capability-gated control plane. `mcp` shows up in
`/v1/server/peers` automatically because health reports `get_local_capabilities()`.

> **Co-location.** filesystem/git MCP servers act on the gateway machine's local disk.
> Tomeberry tale workspaces live where `config/tomeberry/` lives (the `web` node). So by
> default give the **same node both `web` and `mcp`** (or make workspace paths peer-aware).

## Builtins bridge

The 6 legacy builtins (`random_integer`, `generate_name`, `format_voice_segments`,
`save_image_prompt`, `save_wildcard`, `create_ticket`) are exposed over *real* MCP by the
first-party stdio server `app/mcp/builtins_server.py` (the `builtins` roster entry, names
`builtins__*`). `app/mcp/executor.execute()` routes a call by name: a legacy builtin runs
in-process (also the fallback on nodes without `mcp`); anything else is forwarded to the
gateway. `registry.openai_tools_for()` merges builtins + gateway tools into OpenAI schemas
— so the chain LLM step's seam is unchanged.

## Using tools in a chain

Set an `llm` step's `tools` to a list of tool names (builtin or `<server>__<tool>`):

```json
{
  "name": "Pick",
  "type": "llm",
  "tools": ["random_integer", "fs__read_file"],
  "prompt": "Read notes.txt from the workspace, then pick a number for it."
}
```

The step runs an OpenAI tool-use loop (max 6 iterations); both standard `tool_calls` and
llama.cpp's Gemma `<tool_call>…</tool_call>` tokens are handled. Tool names are namespaced
`<server_id>__<tool>` to stay within OpenAI's `[a-zA-Z0-9_-]` charset and avoid collisions.

## Security

External server processes can touch the filesystem. Confine the filesystem server to a
workspace root via its allowed-roots arg (`{workspace_root}`); validate configured roots;
never expose arbitrary roots by default. Tomeberry additionally validates that file paths
fall under a specific tale's `workspace/` before calling.

## The MCP page (`/mcp/`)

Gateway status + start/stop/restart, per-server status with reconnect, the aggregated
tools/resources/prompts lists, and a schema-driven "try it" tester for any tool.

## Gotchas

- The 6-iteration tool-loop cap guards against runaway loops.
- Unknown tool names in `step.tools` are skipped (logged) — the step still runs.
- A flaky MCP server degrades to `down` (with auto-reconnect/backoff) without taking the
  gateway down; the other servers keep working.
- `mcp` pulls a newer `starlette` than FastAPI 0.115 allows, so `requirements.txt` pins
  `starlette==0.46.2`. The gateway only uses the mcp *client* + low-level stdio server,
  neither of which needs starlette's SSE server.
