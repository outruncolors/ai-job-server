"""Tests for app.embed_lab.router — the playground KNN + compare surface.

The embed server is faked at the embed_texts seam (patched per test), so these
exercise the whole route → db → sqlite-vec path without needing the real
gpu.local:8081 server. If sqlite-vec is missing on the host, the KNN tests are
skipped — exactly mirroring how the routes behave in production.
"""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.embed_lab import db as lab_db
from app.embed_lab import router as lab_router


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh playground db per test; embed_texts stays patched per-test."""
    db_path = tmp_path / "playground.db"
    monkeypatch.setattr(lab_db, "DB_PATH", db_path)
    lab_db.reset_connection()
    yield TestClient(main_module.app)
    lab_db.reset_connection()


def _patch_embed(monkeypatch, vectors_by_text):
    """Patch the embed_texts symbol used inside lab_router (imported lazily)."""
    async def fake(texts, *, is_query=False):
        # Hand-built deterministic vectors keyed by text; pad to 384 dims.
        out = []
        for t in texts:
            v = list(vectors_by_text.get(t, [0.0] * 384))
            if len(v) < 384:
                v = v + [0.0] * (384 - len(v))
            elif len(v) > 384:
                v = v[:384]
            out.append(v)
        return out

    monkeypatch.setattr(
        "app.apps.blaboratory.embeddings.embed_texts", fake
    )


def _unit(*nonzeros: tuple[int, float]) -> list[float]:
    """Build a sparse 384-dim vector by index."""
    v = [0.0] * 384
    for i, x in nonzeros:
        v[i] = x
    return v


# ── Compare ─────────────────────────────────────────────────────────────────

def test_compare_returns_square_matrix(client, monkeypatch):
    _patch_embed(monkeypatch, {
        "a": _unit((0, 1.0)),
        "b": _unit((0, 1.0)),       # identical to a
        "c": _unit((1, 1.0)),       # orthogonal
    })
    r = client.post("/v1/embed-lab/compare", json={"texts": ["a", "b", "c"]})
    assert r.status_code == 200
    body = r.json()
    assert body["texts"] == ["a", "b", "c"]
    assert body["dim"] == 384
    sim = body["similarity"]
    assert len(sim) == 3 and all(len(row) == 3 for row in sim)
    # Diagonal is 1.0
    for i in range(3):
        assert sim[i][i] == pytest.approx(1.0, abs=1e-6)
    # a vs b identical, a vs c orthogonal
    assert sim[0][1] == pytest.approx(1.0, abs=1e-6)
    assert sim[0][2] == pytest.approx(0.0, abs=1e-6)
    # Symmetric
    for i in range(3):
        for j in range(3):
            assert sim[i][j] == pytest.approx(sim[j][i], abs=1e-9)


def test_compare_503s_when_embed_unavailable(client, monkeypatch):
    from app.chain.llm_client import EmbedError

    async def boom(texts, *, is_query=False):
        raise EmbedError("server down")

    monkeypatch.setattr("app.apps.blaboratory.embeddings.embed_texts", boom)

    r = client.post("/v1/embed-lab/compare", json={"texts": ["x", "y"]})
    assert r.status_code == 503
    assert "embed_server_unavailable" in r.json()["detail"]


# ── Docs CRUD + KNN ─────────────────────────────────────────────────────────

def _probe_vec_loadable() -> bool:
    """Try importing + loading sqlite-vec into a throwaway connection at
    collection time, so the skip decorator below reflects the real state."""
    import sqlite3
    try:
        import sqlite_vec  # type: ignore
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.close()
        return True
    except Exception:
        return False


vec_required = pytest.mark.skipif(
    not _probe_vec_loadable(),
    reason="sqlite-vec not loadable on this host",
)


def _ensure_vec(client):
    # Force the lab db's lazy connection so VEC_AVAILABLE flips on for the
    # routes that gate on it.
    client.get("/v1/embed-lab/status")


@vec_required
def test_add_list_delete_roundtrip(client, monkeypatch):
    _patch_embed(monkeypatch, {
        "hello world": _unit((0, 1.0)),
        "another doc": _unit((1, 1.0)),
    })
    _ensure_vec(client)

    r = client.post("/v1/embed-lab/docs", json={"text": "hello world"})
    assert r.status_code == 200
    d1 = r.json()
    assert d1["text"] == "hello world"
    assert d1["id"] >= 1

    r = client.post("/v1/embed-lab/docs", json={"text": "another doc"})
    d2 = r.json()
    assert d2["id"] != d1["id"]

    r = client.get("/v1/embed-lab/docs")
    docs = r.json()
    assert [d["id"] for d in docs] == [d2["id"], d1["id"]]  # newest-first

    r = client.delete(f"/v1/embed-lab/docs/{d1['id']}")
    assert r.status_code == 200
    assert client.get("/v1/embed-lab/docs").json() == [
        {"id": d2["id"], "text": "another doc", "created_at": d2["created_at"]}
    ]

    r = client.delete(f"/v1/embed-lab/docs/{d1['id']}")
    assert r.status_code == 404


@vec_required
def test_query_returns_nearest_first(client, monkeypatch):
    _patch_embed(monkeypatch, {
        "alice baked a pie":  _unit((0, 1.0)),
        "bob fixed a radio":  _unit((1, 1.0)),
        "dessert was served": _unit((0, 0.95), (2, 0.05)),  # closest to "alice baked"
        "WHAT DID ALICE COOK": _unit((0, 1.0)),              # the query vector
    })
    _ensure_vec(client)
    for t in ["alice baked a pie", "bob fixed a radio", "dessert was served"]:
        client.post("/v1/embed-lab/docs", json={"text": t})

    r = client.post("/v1/embed-lab/query", json={"query": "WHAT DID ALICE COOK", "k": 3})
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert len(hits) == 3
    # Nearest is "alice baked" (identical), then "dessert was served", then bob.
    assert hits[0]["text"] == "alice baked a pie"
    assert hits[1]["text"] == "dessert was served"
    assert hits[2]["text"] == "bob fixed a radio"
    # Distances are nondecreasing
    assert hits[0]["distance"] <= hits[1]["distance"] <= hits[2]["distance"]


@vec_required
def test_clear_wipes_everything(client, monkeypatch):
    _patch_embed(monkeypatch, {"x": _unit((0, 1.0)), "y": _unit((1, 1.0))})
    _ensure_vec(client)
    client.post("/v1/embed-lab/docs", json={"text": "x"})
    client.post("/v1/embed-lab/docs", json={"text": "y"})
    assert len(client.get("/v1/embed-lab/docs").json()) == 2
    r = client.delete("/v1/embed-lab/docs")
    assert r.status_code == 200
    assert client.get("/v1/embed-lab/docs").json() == []


# ── Status ──────────────────────────────────────────────────────────────────

def test_status_reports_db_state(client):
    r = client.get("/v1/embed-lab/status")
    assert r.status_code == 200
    body = r.json()
    assert "vec_available" in body
    assert body["doc_count"] == 0
    assert body["embedding_dim"] == 384
