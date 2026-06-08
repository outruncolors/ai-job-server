"""MCP gateway runtime config + the roster of MCP servers to connect to.

Two files, both gitignored under ``config/`` (mirrors ``app/llamacpp/config.py``):

- ``config/mcp.json``         — gateway process config (host/port/python/entrypoint).
- ``config/mcp_servers.json`` — the roster of real MCP servers to connect to,
  Claude-Desktop-style (each entry is a stdio ``{command,args,env}`` or a
  Streamable-HTTP ``{url}``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH: Path = Path(
    os.environ.get(
        "MCP_CONFIG_PATH",
        str(PROJECT_ROOT / "config" / "mcp.json"),
    )
)
SERVERS_PATH: Path = Path(
    os.environ.get(
        "MCP_SERVERS_PATH",
        str(PROJECT_ROOT / "config" / "mcp_servers.json"),
    )
)

# Default sandbox root that the ``{workspace_root}`` template in a stdio server's
# args expands to. Per-tale confinement narrows this further at call time
# (Tomeberry validates that file paths fall under a specific tale's workspace/).
DEFAULT_WORKSPACE_ROOT = str(PROJECT_ROOT / "config" / "tomeberry" / "tales")

_config: Optional["MCPConfig"] = None
_servers: Optional["MCPServersConfig"] = None


class MCPConfig(BaseModel):
    """Runtime config for the MCP gateway *process* (mirrors LlamaCppConfig)."""

    host: str = "127.0.0.1"
    port: int = 8082
    autostart: bool = True
    # The platform Python (3.13 venv) used to spawn the gateway.
    python: str = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    # Module entrypoint run as ``python -m <entrypoint>``.
    entrypoint: str = "app.mcp.gateway"
    # Root the ``{workspace_root}`` template expands to for stdio servers.
    workspace_root: str = DEFAULT_WORKSPACE_ROOT


class MCPServerSpec(BaseModel):
    """One MCP server in the roster (stdio child or Streamable-HTTP endpoint)."""

    id: str
    transport: Literal["stdio", "http"] = "stdio"
    # stdio
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # http (Streamable HTTP)
    url: Optional[str] = None
    # Set false to keep an entry in the roster without connecting to it.
    enabled: bool = True


class MCPServersConfig(BaseModel):
    servers: list[MCPServerSpec] = Field(default_factory=list)


def _default_servers() -> MCPServersConfig:
    """A safe default roster: the first-party stub server only.

    The official filesystem/git servers (npx/uvx) are intentionally NOT enabled
    by default — operators add them to ``config/mcp_servers.json`` once the tools
    they need are installed and a workspace root is chosen.
    """
    return MCPServersConfig(
        servers=[
            MCPServerSpec(
                id="builtins",
                transport="stdio",
                command=str(PROJECT_ROOT / ".venv" / "bin" / "python"),
                args=["-m", "app.mcp.builtins_server"],
            ),
        ]
    )


def load_config() -> MCPConfig:
    global _config
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _config = MCPConfig(**data)
            return _config
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    _config = MCPConfig()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_config.model_dump_json(indent=2), encoding="utf-8")
    return _config


def save_config(config: MCPConfig) -> None:
    global _config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    _config = config


def get_config() -> MCPConfig:
    global _config
    if _config is None:
        return load_config()
    return _config


def load_servers() -> MCPServersConfig:
    global _servers
    try:
        if SERVERS_PATH.exists():
            data = json.loads(SERVERS_PATH.read_text(encoding="utf-8"))
            _servers = MCPServersConfig(**data)
            return _servers
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    _servers = _default_servers()
    SERVERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVERS_PATH.write_text(_servers.model_dump_json(indent=2), encoding="utf-8")
    return _servers


def save_servers(servers: MCPServersConfig) -> None:
    global _servers
    SERVERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVERS_PATH.write_text(servers.model_dump_json(indent=2), encoding="utf-8")
    _servers = servers


def get_servers() -> MCPServersConfig:
    global _servers
    if _servers is None:
        return load_servers()
    return _servers


def reset_config() -> None:
    """Drop cached singletons — tests use this between cases."""
    global _config, _servers
    _config = None
    _servers = None
