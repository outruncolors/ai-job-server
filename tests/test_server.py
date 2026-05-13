from __future__ import annotations


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
