from __future__ import annotations

import json


def _write_server_config(tmp_path, payload):
    import app.server as s
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "server.json").write_text(json.dumps(payload), encoding="utf-8")
    s.reset_server_config()


def test_server_stats_shape(client):
    r = client.get("/v1/server/stats")
    assert r.status_code == 200
    body = r.json()
    for key in ("cpu_percent", "memory", "disk", "uptime_seconds", "jobs", "hostname", "python_version"):
        assert key in body, f"missing key: {key}"


def test_server_stats_memory_fields(client):
    body = client.get("/v1/server/stats").json()
    mem = body["memory"]
    assert set(mem.keys()) == {"used", "total", "percent"}
    assert mem["total"] > 0


def test_server_stats_disk_fields(client):
    body = client.get("/v1/server/stats").json()
    disk = body["disk"]
    assert set(disk.keys()) == {"used", "total", "percent"}
    assert disk["total"] > 0


def test_server_stats_job_counts_keys(client):
    body = client.get("/v1/server/stats").json()
    assert set(body["jobs"].keys()) == {"queued", "running", "done", "failed"}


def test_server_stats_uptime_nonnegative(client):
    body = client.get("/v1/server/stats").json()
    assert body["uptime_seconds"] >= 0


def test_server_restart_accepted(client, monkeypatch):
    import app.main as m
    called = []
    monkeypatch.setattr(m, "schedule_restart", lambda: called.append(True))
    r = client.post("/v1/server/restart")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert called  # TestClient runs background tasks synchronously


# ---------- capability helpers ----------


def test_default_capabilities_when_no_config(tmp_path):
    import app.server as s
    s.reset_server_config()
    caps = s.get_local_capabilities()
    assert caps == {"web", "voice", "image", "llm"}
    assert s.get_peers() == []
    assert s.find_peer_for_capability("llm") is None


def test_loads_config_from_disk(tmp_path):
    import app.server as s
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web", "voice", "image"],
        "peers": [
            {"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}
        ],
    })
    assert s.get_local_capabilities() == {"web", "voice", "image"}
    peers = s.get_peers()
    assert len(peers) == 1
    assert peers[0].name == "gpu"
    assert peers[0].host == "gpu.local"
    peer = s.find_peer_for_capability("llm")
    assert peer is not None and peer.host == "gpu.local"


def test_find_peer_returns_none_for_unknown_capability(tmp_path):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web"],
        "peers": [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}],
    })
    import app.server as s
    assert s.find_peer_for_capability("image") is None


def test_malformed_config_falls_back_to_default(tmp_path):
    import app.server as s
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "server.json").write_text("not json", encoding="utf-8")
    s.reset_server_config()
    assert s.get_local_capabilities() == {"web", "voice", "image", "llm"}


# ---------- capability endpoints ----------


def test_get_capabilities_endpoint(client, tmp_path):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web", "voice"],
        "peers": [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}],
    })
    body = client.get("/v1/server/capabilities").json()
    assert body["local"] == ["voice", "web"]
    assert len(body["peers"]) == 1
    assert body["peers"][0]["name"] == "gpu"
    assert body["peers"][0]["capabilities"] == ["llm"]


def test_get_peers_endpoint(client, tmp_path):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web"],
        "peers": [
            {"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]},
            {"name": "render", "host": "render.local", "port": 8090, "capabilities": ["image"]},
        ],
    })
    body = client.get("/v1/server/peers").json()
    assert len(body["peers"]) == 2
    # health placeholder until the poller ticket lands
    assert all(p["health"] is None for p in body["peers"])
    names = sorted(p["name"] for p in body["peers"])
    assert names == ["gpu", "render"]


def test_health_endpoint_includes_git_sha_and_caps(client, tmp_path, monkeypatch):
    import app.server as s
    monkeypatch.setattr(s, "_git_sha_cache", "deadbeef")
    monkeypatch.setattr(s, "_git_sha_loaded", True)
    _write_server_config(tmp_path, {"role": "primary", "capabilities": ["web"], "peers": []})
    body = client.get("/v1/server/health").json()
    assert body["status"] == "ok"
    assert body["git_sha"] == "deadbeef"
    assert body["capabilities"] == ["web"]
    assert body["uptime_seconds"] >= 0
    assert "timestamp" in body


# ---------- 503 capability enforcement ----------


def test_image_route_503_when_capability_missing(client, tmp_path):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web"],
        "peers": [{"name": "render", "host": "render.local", "port": 8090, "capabilities": ["image"]}],
    })
    r = client.post("/v1/jobs/image", json={"workflow": "x", "prompt": "y"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail == {
        "error": "capability_unavailable",
        "needed": "image",
        "where": "render.local",
    }


def test_voice_route_503_when_capability_missing(client, tmp_path):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web"],
        "peers": [{"name": "voicebox", "host": "voicebox.local", "port": 8090, "capabilities": ["voice"]}],
    })
    r = client.post("/v1/jobs/voice", json={"text": "hi"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["error"] == "capability_unavailable"
    assert detail["needed"] == "voice"
    assert detail["where"] == "voicebox.local"


def test_503_where_field_is_unknown_when_no_peer(client, tmp_path):
    _write_server_config(tmp_path, {"role": "primary", "capabilities": ["web"], "peers": []})
    r = client.post("/v1/jobs/image", json={"workflow": "x", "prompt": "y"})
    assert r.status_code == 503
    assert r.json()["detail"]["where"] == "unknown"


def test_comfyui_router_503_when_image_missing(client, tmp_path):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web"],
        "peers": [],
    })
    r = client.get("/v1/comfyui/status")
    assert r.status_code == 503
    assert r.json()["detail"]["needed"] == "image"


def test_omnivoice_router_503_when_voice_missing(client, tmp_path):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web"],
        "peers": [],
    })
    r = client.get("/v1/omnivoice/status")
    assert r.status_code == 503
    assert r.json()["detail"]["needed"] == "voice"


def test_routes_allowed_when_local_has_capability(client, tmp_path, mock_execute_voice_job):
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web", "voice", "image"],
        "peers": [],
    })
    r = client.post("/v1/jobs/voice", json={"text": "hello"})
    # 202 Accepted — capability satisfied, request enters the queue
    assert r.status_code == 202


def test_chain_route_not_gated_by_llm_capability(client, tmp_path, mock_execute_chain_job):
    """Chain jobs orchestrate locally; they call out to a peer for LLM. Don't 503 the route."""
    _write_server_config(tmp_path, {
        "role": "primary",
        "capabilities": ["web"],
        "peers": [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}],
    })
    body = {
        "input": "hi",
        "llm": {"api_base": "http://gpu.local:8080/v1", "model": "gemma"},
        "steps": [{"name": "step1", "type": "llm", "prompt": "say hi"}],
    }
    r = client.post("/v1/jobs/chain", json=body)
    assert r.status_code == 202
