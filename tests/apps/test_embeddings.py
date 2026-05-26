"""D1.2b — embed() client + embeddings config + remote wiring.

httpx is mocked via MockTransport (same patched-__init__ trick as
test_chain_streaming): no live embed server.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.apps.blaboratory import embeddings
from app.chain.llm_client import EmbedError, OpenAICompatibleLLMClient

DIM = 384


@pytest.fixture(autouse=True)
def local_llm_and_tmp_config(tmp_path, monkeypatch):
    # embed_url resolves to localhost when this node is llm-capable
    import app.server as server
    monkeypatch.setattr(server, "get_local_capabilities", lambda: {"web", "llm"})
    # fresh config in tmp
    monkeypatch.setattr(embeddings, "CONFIG_PATH", tmp_path / "embeddings.json")
    monkeypatch.setattr(embeddings, "_config", None)


def _install_transport(monkeypatch, handler):
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _embeddings_response(n: int) -> httpx.Response:
    data = [{"index": i, "embedding": [float(i)] * DIM} for i in range(n)]
    return httpx.Response(200, json={"object": "list", "data": data})


# ---- config ----

def test_config_defaults(tmp_path):
    cfg = embeddings.load_config()
    assert cfg.port == 8081
    assert cfg.dim == DIM
    assert cfg.model == "bge-small"
    assert cfg.query_prefix.startswith("Represent this sentence")
    assert embeddings.CONFIG_PATH.exists()


def test_embed_url_local():
    assert embeddings.embed_url() == "http://127.0.0.1:8081/v1"


# ---- batching ----

async def test_embed_texts_batches_to_n_vectors(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _embeddings_response(3)

    _install_transport(monkeypatch, handler)
    vecs = await embeddings.embed_texts(["a", "b", "c"])
    assert len(vecs) == 3
    assert all(len(v) == DIM for v in vecs)
    assert captured["url"].endswith("/v1/embeddings")
    assert captured["body"]["input"] == ["a", "b", "c"]  # raw, no prefix
    assert captured["body"]["model"] == "bge-small"


async def test_query_prefix_applied_only_for_queries(monkeypatch):
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return _embeddings_response(len(body["input"]))

    _install_transport(monkeypatch, handler)

    await embeddings.embed_texts(["cat"], is_query=False)
    await embeddings.embed_texts(["cat"], is_query=True)

    prefix = embeddings.get_config().query_prefix
    assert bodies[0]["input"] == ["cat"]
    assert bodies[1]["input"] == [prefix + "cat"]


async def test_empty_input_short_circuits(monkeypatch):
    def handler(request):  # should never be called
        raise AssertionError("no request expected for empty input")

    _install_transport(monkeypatch, handler)
    assert await embeddings.embed_texts([]) == []


# ---- error mapping ----

async def test_connect_error_maps_to_embed_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _install_transport(monkeypatch, handler)
    with pytest.raises(EmbedError):
        await embeddings.embed_texts(["x"])


async def test_http_error_maps_to_embed_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _install_transport(monkeypatch, handler)
    with pytest.raises(EmbedError):
        await embeddings.embed_texts(["x"])


async def test_timeout_maps_to_embed_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    _install_transport(monkeypatch, handler)
    with pytest.raises(EmbedError):
        await embeddings.embed_texts(["x"])


async def test_client_embed_direct_orders_by_index(monkeypatch):
    """Out-of-order response items are returned in input/index order."""
    def handler(request: httpx.Request) -> httpx.Response:
        data = [
            {"index": 2, "embedding": [2.0] * DIM},
            {"index": 0, "embedding": [0.0] * DIM},
            {"index": 1, "embedding": [1.0] * DIM},
        ]
        return httpx.Response(200, json={"data": data})

    _install_transport(monkeypatch, handler)
    client = OpenAICompatibleLLMClient()
    vecs = await client.embed(["a", "b", "c"], api_base="http://fake/v1", model="m")
    assert [v[0] for v in vecs] == [0.0, 1.0, 2.0]
