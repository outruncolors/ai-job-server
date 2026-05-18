from __future__ import annotations

import json

import httpx
import pytest


def _write_server_config(tmp_path, payload):
    import app.server as s
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "server.json").write_text(json.dumps(payload), encoding="utf-8")
    s.reset_server_config()


def _peers_config(tmp_path, peers):
    _write_server_config(
        tmp_path,
        {"role": "primary", "capabilities": ["web"], "peers": peers},
    )


@pytest.fixture(autouse=True)
def _reset_peer_health():
    import app.peer_health as ph
    ph.reset_peer_health()
    yield
    ph.reset_peer_health()


async def test_poll_marks_green_when_sha_matches(tmp_path, monkeypatch):
    import app.peer_health as ph
    import app.server as s
    _peers_config(tmp_path, [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}])
    monkeypatch.setattr(s, "_git_sha_cache", "deadbeef")
    monkeypatch.setattr(s, "_git_sha_loaded", True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/server/health"
        return httpx.Response(200, json={"git_sha": "deadbeef", "capabilities": ["llm"]})

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        ph.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    await ph.poll_once()
    snap = ph.get_peer_health_snapshot()
    assert "gpu" in snap
    assert snap["gpu"]["status"] == "green"
    assert snap["gpu"]["git_sha"] == "deadbeef"
    assert snap["gpu"]["last_seen"] is not None
    assert snap["gpu"]["error"] is None
    assert snap["gpu"]["host"] == "gpu.local"


async def test_poll_marks_amber_when_sha_differs(tmp_path, monkeypatch):
    import app.peer_health as ph
    import app.server as s
    _peers_config(tmp_path, [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}])
    monkeypatch.setattr(s, "_git_sha_cache", "deadbeef")
    monkeypatch.setattr(s, "_git_sha_loaded", True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"git_sha": "cafef00d", "capabilities": ["llm"]})

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        ph.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    await ph.poll_once()
    snap = ph.get_peer_health_snapshot()
    assert snap["gpu"]["status"] == "amber"
    assert snap["gpu"]["git_sha"] == "cafef00d"


async def test_poll_marks_red_on_connection_failure(tmp_path, monkeypatch):
    import app.peer_health as ph
    _peers_config(tmp_path, [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        ph.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    await ph.poll_once()
    snap = ph.get_peer_health_snapshot()
    assert snap["gpu"]["status"] == "red"
    assert snap["gpu"]["error"]
    # last_seen and git_sha stay None on the very first failed poll
    assert snap["gpu"]["last_seen"] is None


async def test_poll_marks_red_on_5xx(tmp_path, monkeypatch):
    import app.peer_health as ph
    _peers_config(tmp_path, [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="overloaded")

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        ph.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    await ph.poll_once()
    snap = ph.get_peer_health_snapshot()
    assert snap["gpu"]["status"] == "red"
    assert "503" in (snap["gpu"]["error"] or "")


async def test_poll_preserves_last_seen_after_failure(tmp_path, monkeypatch):
    import app.peer_health as ph
    import app.server as s
    _peers_config(tmp_path, [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}])
    monkeypatch.setattr(s, "_git_sha_cache", "deadbeef")
    monkeypatch.setattr(s, "_git_sha_loaded", True)

    responses = iter([
        httpx.Response(200, json={"git_sha": "deadbeef"}),
        httpx.Response(503, text="boom"),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        ph.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    await ph.poll_once()
    first_seen = ph.get_peer_health_snapshot()["gpu"]["last_seen"]
    assert first_seen is not None

    await ph.poll_once()
    snap = ph.get_peer_health_snapshot()
    assert snap["gpu"]["status"] == "red"
    # Sticky from the prior successful poll
    assert snap["gpu"]["last_seen"] == first_seen
    assert snap["gpu"]["git_sha"] == "deadbeef"


async def test_poll_drops_removed_peers(tmp_path, monkeypatch):
    import app.peer_health as ph
    _peers_config(tmp_path, [
        {"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]},
        {"name": "render", "host": "render.local", "port": 8090, "capabilities": ["image"]},
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"git_sha": "abc"})

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        ph.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    await ph.poll_once()
    assert set(ph.get_peer_health_snapshot().keys()) == {"gpu", "render"}

    # Re-config with only one peer
    _peers_config(tmp_path, [
        {"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]},
    ])
    await ph.poll_once()
    assert set(ph.get_peer_health_snapshot().keys()) == {"gpu"}


def test_peers_endpoint_returns_health_snapshot(client, tmp_path, monkeypatch):
    import app.peer_health as ph
    import app.server as s
    _peers_config(tmp_path, [
        {"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]},
    ])
    monkeypatch.setattr(s, "_git_sha_cache", "deadbeef", raising=False)
    monkeypatch.setattr(s, "_git_sha_loaded", True, raising=False)
    # Seed the snapshot directly — the poller doesn't run under TestClient.
    ph._health["gpu"] = {
        "status": "green",
        "git_sha": "deadbeef",
        "last_seen": "2026-05-17T00:00:00+00:00",
        "error": None,
        "host": "gpu.local",
        "port": 8090,
    }
    body = client.get("/v1/server/peers").json()
    assert body["local_git_sha"] == "deadbeef"
    assert len(body["peers"]) == 1
    p0 = body["peers"][0]
    assert p0["name"] == "gpu"
    assert p0["health"]["status"] == "green"
    assert p0["health"]["git_sha"] == "deadbeef"
