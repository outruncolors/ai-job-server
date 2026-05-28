"""Embed Lab routes — a blaboratory-free playground for the embed model and the
vector index. Owns its own SQLite db (`config/embed-lab/playground.db`) so
experimentation here can't pollute the sim's `blaboratory.db`.

Endpoints (all under `/v1/embed-lab`):

  POST   /compare   {"texts": ["a","b",...]}  → similarity matrix + the vectors
  POST   /docs      {"text": "..."}           → embed + store, returns the doc
  GET    /docs                                → list every stored doc
  DELETE /docs/{id}                           → drop one doc + its vector
  DELETE /docs                                → wipe the playground
  POST   /query     {"query":"...","k":10}    → KNN hits with distance + text

Embeddings are computed via `app.apps.blaboratory.embeddings.embed_texts`,
which is just a thin HTTP client over the gpu.local :8081 embed server (not
sim-specific). KNN runs locally on the playground db.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db as lab_db

router = APIRouter(prefix="/v1/embed-lab", tags=["embed-lab"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class CompareResponse(BaseModel):
    texts: list[str]
    dim: int
    # similarity[i][j] = cosine(texts[i], texts[j]), in [-1, 1]
    similarity: list[list[float]]


class AddDocRequest(BaseModel):
    text: str = Field(min_length=1)


class Doc(BaseModel):
    id: int
    text: str
    created_at: str


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=200)


class QueryHit(BaseModel):
    doc_id: int
    text: str
    distance: float


class QueryResponse(BaseModel):
    query: str
    hits: list[QueryHit]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(y * y for y in b)) or 1e-12
    return dot / (na * nb)


async def _embed(texts: list[str], *, is_query: bool) -> list[list[float]]:
    """Wrap embed_texts so the caller sees an HTTPException, not an EmbedError."""
    from app.apps.blaboratory.embeddings import embed_texts, EmbedError

    try:
        return await embed_texts(texts, is_query=is_query)
    except EmbedError as e:
        raise HTTPException(
            status_code=503,
            detail=f"embed_server_unavailable: {e}",
        )


def _require_vec() -> None:
    if not lab_db.VEC_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="sqlite_vec_unavailable: extension failed to load; KNN disabled",
        )


def _serialize(vec: list[float]) -> bytes:
    import sqlite_vec  # type: ignore

    return sqlite_vec.serialize_float32(vec)


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/compare", response_model=CompareResponse)
async def compare(req: CompareRequest):
    """Embed N texts and return the NxN cosine-similarity matrix."""
    # Documents are embedded without the query prefix — comparing apples to apples.
    vecs = await _embed(req.texts, is_query=False)
    n = len(vecs)
    sim = [[_cosine(vecs[i], vecs[j]) for j in range(n)] for i in range(n)]
    return CompareResponse(texts=req.texts, dim=len(vecs[0]) if vecs else 0, similarity=sim)


@router.post("/docs", response_model=Doc)
async def add_doc(req: AddDocRequest):
    """Embed a single text and store it in the playground index."""
    _require_vec()
    vecs = await _embed([req.text], is_query=False)
    conn = lab_db.get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO docs (text, created_at) VALUES (?, ?)",
            (req.text, _now_iso()),
        )
        doc_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO vec_docs (embedding, doc_id) VALUES (?, ?)",
            (_serialize(vecs[0]), doc_id),
        )
    row = conn.execute("SELECT id, text, created_at FROM docs WHERE id = ?", (doc_id,)).fetchone()
    return Doc(id=row["id"], text=row["text"], created_at=row["created_at"])


@router.get("/docs", response_model=list[Doc])
def list_docs():
    """List every doc in the playground, newest first."""
    conn = lab_db.get_connection()
    rows = conn.execute(
        "SELECT id, text, created_at FROM docs ORDER BY id DESC"
    ).fetchall()
    return [Doc(id=r["id"], text=r["text"], created_at=r["created_at"]) for r in rows]


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int):
    """Drop one doc + its vector row."""
    conn = lab_db.get_connection()
    with conn:
        if lab_db.VEC_AVAILABLE:
            conn.execute("DELETE FROM vec_docs WHERE doc_id = ?", (doc_id,))
        cur = conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="not_found")
    return {"deleted": doc_id}


@router.delete("/docs")
def clear_docs():
    """Wipe every doc + vector from the playground."""
    conn = lab_db.get_connection()
    with conn:
        if lab_db.VEC_AVAILABLE:
            conn.execute("DELETE FROM vec_docs")
        conn.execute("DELETE FROM docs")
    return {"cleared": True}


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """K-nearest playground docs for a query string (bge prefix applied)."""
    _require_vec()
    qvecs = await _embed([req.query], is_query=True)
    qvec = qvecs[0]
    conn = lab_db.get_connection()
    rows = conn.execute(
        """
        SELECT v.doc_id AS doc_id, v.distance AS distance, d.text AS text
        FROM vec_docs v
        JOIN docs d ON d.id = v.doc_id
        WHERE v.embedding MATCH ? AND k = ?
        ORDER BY v.distance
        """,
        (_serialize(qvec), req.k),
    ).fetchall()
    hits = [
        QueryHit(doc_id=int(r["doc_id"]), text=r["text"], distance=float(r["distance"]))
        for r in rows
    ]
    return QueryResponse(query=req.query, hits=hits)


@router.get("/status")
def status():
    """Snapshot of the lab state: vec extension availability + doc count."""
    conn = lab_db.get_connection()
    count = conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"]
    return {
        "vec_available": lab_db.VEC_AVAILABLE,
        "doc_count": int(count),
        "embedding_dim": lab_db.EMBEDDING_DIM,
    }
