"""``/v1/textdiff`` — make / inspect / apply text proposals (app-agnostic).

Thin HTTP surface over :mod:`app.textdiff.diff` + :mod:`app.textdiff.store`. Apps
usually call the Python API directly; these routes exist for inspection and for a
frontend that wants to preview an edit without owning the diff logic.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import store
from .diff import ConflictError, apply_proposal, make_proposal, render_inline

router = APIRouter(prefix="/v1/textdiff", tags=["textdiff"])


class MakeBody(BaseModel):
    before: str = ""
    after: str = ""
    mode: str = "replace"
    app: str | None = None
    scope_key: str | None = None


class ApplyBody(BaseModel):
    current: str
    accept_hunks: list[int] | None = None
    force: bool = False


@router.post("/make")
async def make(body: MakeBody):
    proposal = make_proposal(body.before, body.after, body.mode)
    if body.app and body.scope_key:
        store.save_proposal(body.app, body.scope_key, proposal)
    return {
        "proposal": proposal.model_dump(),
        "segments": [s.model_dump() for s in render_inline(proposal)],
    }


@router.get("/{app}/{scope_key}")
async def list_for_scope(app: str, scope_key: str):
    return {"proposals": [p.model_dump() for p in store.list_proposals(app, scope_key)]}


@router.get("/{app}/{scope_key}/{proposal_id}")
async def get_one(app: str, scope_key: str, proposal_id: str):
    p = store.get_proposal(app, scope_key, proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return {"proposal": p.model_dump(), "segments": [s.model_dump() for s in render_inline(p)]}


@router.post("/{app}/{scope_key}/{proposal_id}/apply")
async def apply_one(app: str, scope_key: str, proposal_id: str, body: ApplyBody):
    p = store.get_proposal(app, scope_key, proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    try:
        result = apply_proposal(body.current, p, body.accept_hunks, force=body.force)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"result": result}
