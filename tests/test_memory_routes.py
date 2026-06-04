from __future__ import annotations


def _scope():
    return {"scope_type": "project", "scope_id": "ai-job-server"}


def test_health(client):
    r = client.get("/v1/memory/health")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["backend"] == "plain"
    assert body["index_available"] is True


def test_write_returns_id_and_path(client):
    r = client.post(
        "/v1/memory/write",
        json={"title": "Atomic UI", "body": "prefers atomic tests", "scope": _scope()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["memory_id"].startswith("mem_")
    assert body["path"].endswith(".md")


def test_list_returns_metadata_total_and_no_body(client):
    client.post("/v1/memory/write",
                json={"title": "Alpha", "body": "secret body alpha", "scope": _scope(), "tags": ["x"]})
    client.post("/v1/memory/write",
                json={"title": "Beta", "body": "secret body beta",
                      "scope": {"scope_type": "app", "scope_id": "hoodat"}})
    r = client.get("/v1/memory/list")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["total"] == 2
    titles = {it["title"] for it in body["items"]}
    assert titles == {"Alpha", "Beta"}
    # The table listing carries metadata only — never the body.
    first = body["items"][0]
    assert "body" not in first
    assert set(["id", "title", "scope_type", "scope_id", "tags", "updated_at"]).issubset(first)


def test_list_scope_filter(client):
    client.post("/v1/memory/write",
                json={"title": "Alpha", "body": "a", "scope": _scope()})
    client.post("/v1/memory/write",
                json={"title": "Beta", "body": "b", "scope": {"scope_type": "app", "scope_id": "hoodat"}})
    r = client.get("/v1/memory/list", params={"scope_type": "app", "scope_id": "hoodat"})
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["title"] == "Beta"


def test_list_pagination(client):
    for i in range(3):
        client.post("/v1/memory/write",
                    json={"title": f"M{i}", "body": "b", "scope": _scope()})
    page1 = client.get("/v1/memory/list", params={"limit": 2, "offset": 0}).json()
    assert page1["total"] == 3 and len(page1["items"]) == 2
    page2 = client.get("/v1/memory/list", params={"limit": 2, "offset": 2}).json()
    assert page2["total"] == 3 and len(page2["items"]) == 1


def test_write_then_search_scope_filtered(client):
    client.post(
        "/v1/memory/write",
        json={"title": "Lighthouse", "body": "north of the harbor", "scope": _scope()},
    )
    # right scope → hit
    r = client.post(
        "/v1/memory/search",
        json={"query": "lighthouse", "scopes": [_scope()], "top_k": 5},
    )
    assert r.json()["count"] == 1
    # wrong scope → miss
    r2 = client.post(
        "/v1/memory/search",
        json={"query": "lighthouse", "scopes": [{"scope_type": "app", "scope_id": "hoodat"}]},
    )
    assert r2.json()["count"] == 0


def test_read_roundtrip_and_404(client):
    w = client.post(
        "/v1/memory/write",
        json={"title": "Note", "body": "hello body", "scope": _scope()},
    ).json()
    r = client.get(f"/v1/memory/read/{w['memory_id']}")
    assert r.status_code == 200
    assert r.json()["memory"]["body"] == "hello body"
    assert client.get("/v1/memory/read/mem_missing").status_code == 404


def test_delete_excludes_from_search(client):
    w = client.post(
        "/v1/memory/write",
        json={"title": "Lighthouse", "body": "the lighthouse", "scope": _scope()},
    ).json()
    client.post(f"/v1/memory/delete/{w['memory_id']}")
    r = client.post("/v1/memory/search", json={"query": "lighthouse", "scopes": [_scope()]})
    assert r.json()["count"] == 0


def test_reindex(client):
    client.post(
        "/v1/memory/write",
        json={"title": "x", "body": "y", "scope": _scope()},
    )
    r = client.post("/v1/memory/reindex", json={"scopes": [_scope()], "force": True})
    assert r.status_code == 200 and r.json()["ok"]


def test_scopes_lists_types(client):
    r = client.get("/v1/memory/scopes")
    assert r.status_code == 200
    assert "project" in r.json()["scope_types"]


def test_demo_seed_run_reset_confined(client):
    # a real memory in another scope must survive the demo reset
    real = client.post(
        "/v1/memory/write",
        json={"title": "Real", "body": "keep me", "scope": _scope()},
    ).json()

    seeded = client.post("/v1/memory/test/seed-demo").json()
    assert len(seeded["memories"]) == 4
    assert seeded["scope"]["scope_type"] == "test"

    runs = client.post("/v1/memory/test/run-demo-searches").json()
    assert all(s["ok"] for s in runs["searches"]), runs

    reset = client.post("/v1/memory/test/reset").json()
    assert reset["removed"] == 4
    # real survives
    assert client.get(f"/v1/memory/read/{real['memory_id']}").status_code == 200
