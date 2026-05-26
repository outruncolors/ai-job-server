"""Embedding config + remote wiring for Blaboratory vector retrieval (D1.2b).

The vector index lives on the web node, but embeddings are computed by the
app-managed embed ``llama-server`` (D1.2a) on the ``llm`` node. This module:

- loads/persists a small config (``config/blaboratory/embeddings.json``):
  ``port`` / ``model`` / ``dim`` / ``query_prefix``;
- resolves the embed endpoint URL — **host follows the ``llm`` peer**
  (``find_peer_for_capability("llm")``) like the chat data plane, just a
  different port — so there's no separate host config;
- exposes ``embed_texts(texts, *, is_query)`` which applies the bge query
  instruction prefix to *queries only* (document/query asymmetry) and calls
  the shared :class:`OpenAICompatibleLLMClient`.

``dim`` is informational here (the schema hard-codes 384); it lives in config so
a model change is a single, visible edit alongside the re-index note.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from ...chain.llm_client import EmbedError, OpenAICompatibleLLMClient

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH: Path = PROJECT_ROOT / "config" / "blaboratory" / "embeddings.json"

_config: Optional["EmbeddingsConfig"] = None

# bge-small wants this instruction prefix on the *query* side only.
_DEFAULT_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingsConfig(BaseModel):
    port: int = 8081
    model: str = "bge-small"
    dim: int = 384
    query_prefix: str = _DEFAULT_QUERY_PREFIX


def load_config() -> EmbeddingsConfig:
    global _config
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            _config = EmbeddingsConfig(**data)
            return _config
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    _config = EmbeddingsConfig()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_config.model_dump_json(indent=2), encoding="utf-8")
    return _config


def save_config(config: EmbeddingsConfig) -> None:
    global _config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    _config = config


def get_config() -> EmbeddingsConfig:
    global _config
    if _config is None:
        return load_config()
    return _config


def embed_url() -> str:
    """``http://<host>:<embed_port>/v1`` for the embed server.

    Host is the ``llm`` node: ``127.0.0.1`` when this node is llm-capable, else
    the ``llm`` peer's host. Port comes from this module's config.
    """
    from ...server import find_peer_for_capability, get_local_capabilities

    port = get_config().port
    if "llm" in get_local_capabilities():
        return f"http://127.0.0.1:{port}/v1"
    peer = find_peer_for_capability("llm")
    if peer is None:
        raise EmbedError(
            "no node with 'llm' capability available for embeddings "
            "(neither local nor any configured peer)"
        )
    return f"http://{peer.host}:{port}/v1"


async def embed_texts(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """Embed ``texts`` → vectors in input order.

    When ``is_query`` the bge query-instruction prefix is prepended to each text
    (documents are embedded raw). Raises :class:`EmbedError` on any failure.
    """
    if not texts:
        return []
    cfg = get_config()
    if is_query:
        texts = [cfg.query_prefix + t for t in texts]
    client = OpenAICompatibleLLMClient()
    return await client.embed(texts, api_base=embed_url(), model=cfg.model)
