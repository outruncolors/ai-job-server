"""Tomeberry HTTP surface (``/v1/apps/tomeberry/...``).

Phase 2 covers tales + concepts + hierarchy + links + premise CRUD, plus
read-only assistant/trace access. The assistant request pipeline
(``/requests`, accept/reject/iterate) is added by the generation phases.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import prompts as _prompts  # noqa: F401 — import-time register_all()
from . import store
from .models import (
    ConceptCreate,
    ConceptPatch,
    LinkCreate,
    MoveBody,
    PremiseUpdate,
    TaleCreate,
    TaleUpdate,
)

router = APIRouter(prefix="/v1/apps/tomeberry", tags=["tomeberry"])


# ---- tales -----------------------------------------------------------------


@router.get("/tales")
def list_tales():
    return {"tales": store.list_tales()}


@router.post("/tales", status_code=201)
def create_tale(body: TaleCreate):
    return store.create_tale(body.model_dump())


@router.get("/tales/{tid}")
def get_tale(tid: str):
    tale = store.get_tale(tid)
    if tale is None:
        raise HTTPException(status_code=404, detail="tale not found")
    return {
        "tale": tale,
        "hierarchy": store.get_hierarchy(tid),
        "concepts": store.list_concepts(tid),
    }


@router.patch("/tales/{tid}")
def update_tale(tid: str, body: TaleUpdate):
    tale = store.update_tale(tid, body.model_dump(exclude_none=True))
    if tale is None:
        raise HTTPException(status_code=404, detail="tale not found")
    return tale


@router.delete("/tales/{tid}", status_code=204)
def delete_tale(tid: str):
    if not store.delete_tale(tid):
        raise HTTPException(status_code=404, detail="tale not found")


@router.put("/tales/{tid}/premise")
def set_premise(tid: str, body: PremiseUpdate):
    tale = store.get_tale(tid)
    if tale is None:
        raise HTTPException(status_code=404, detail="tale not found")
    pid = tale.get("premise_id")
    from .models import HistoryEntry

    if pid and store.get_concept(tid, pid) is not None:
        return store.update_concept(
            tid,
            pid,
            {"body": body.body},
            history=HistoryEntry(at=store._now(), kind="manual_edit", summary="premise edited"),
        )
    concept = store.create_concept(
        tid,
        {"concept_class": "narrative_construct", "type": "premise", "title": "Premise", "body": body.body},
    )
    store.update_tale(tid, {})  # touch
    tale["premise_id"] = concept["id"]
    store._atomic_write(store._tale_file(tid), tale)
    return concept


# ---- concepts --------------------------------------------------------------


@router.get("/tales/{tid}/concepts")
def list_concepts(tid: str, concept_class: str | None = None, type: str | None = None):
    if store.get_tale(tid) is None:
        raise HTTPException(status_code=404, detail="tale not found")
    return {"concepts": store.list_concepts(tid, concept_class, type)}


@router.post("/tales/{tid}/concepts", status_code=201)
def create_concept(tid: str, body: ConceptCreate):
    concept = store.create_concept(tid, body.model_dump())
    if concept is None:
        raise HTTPException(status_code=404, detail="tale not found")
    return concept


@router.get("/tales/{tid}/concepts/{cid}")
def get_concept(tid: str, cid: str):
    concept = store.get_concept(tid, cid)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return concept


@router.patch("/tales/{tid}/concepts/{cid}")
def patch_concept(tid: str, cid: str, body: ConceptPatch):
    from .models import HistoryEntry

    concept = store.update_concept(
        tid,
        cid,
        body.model_dump(exclude_none=True),
        history=HistoryEntry(at=store._now(), kind="manual_edit", summary="edited"),
    )
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return concept


@router.delete("/tales/{tid}/concepts/{cid}", status_code=204)
def delete_concept(tid: str, cid: str):
    if not store.delete_concept(tid, cid):
        raise HTTPException(status_code=404, detail="concept not found")


@router.get("/tales/{tid}/hierarchy")
def get_hierarchy(tid: str):
    h = store.get_hierarchy(tid)
    if h is None:
        raise HTTPException(status_code=404, detail="tale not found")
    return h


@router.post("/tales/{tid}/concepts/{cid}/move")
def move_concept(tid: str, cid: str, body: MoveBody):
    concept = store.move_concept(tid, cid, body.parent_id, body.order)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return concept


@router.post("/tales/{tid}/concepts/{cid}/links")
def add_link(tid: str, cid: str, body: LinkCreate):
    concept = store.add_link(tid, cid, body.model_dump())
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return concept


@router.delete("/tales/{tid}/concepts/{cid}/links/{rel}/{target}")
def remove_link(tid: str, cid: str, rel: str, target: str):
    concept = store.remove_link(tid, cid, rel, target)
    if concept is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return concept


# ---- assistant + traces (read) --------------------------------------------


@router.get("/tales/{tid}/assistant")
def get_assistant(tid: str):
    if store.get_tale(tid) is None:
        raise HTTPException(status_code=404, detail="tale not found")
    return store.get_assistant(tid)


@router.get("/tales/{tid}/requests")
def list_requests(tid: str):
    if store.get_tale(tid) is None:
        raise HTTPException(status_code=404, detail="tale not found")
    return {"requests": store.list_traces(tid)}


@router.get("/tales/{tid}/requests/{rid}")
def get_request(tid: str, rid: str):
    trace = store.get_trace(tid, rid)
    if trace is None:
        raise HTTPException(status_code=404, detail="request not found")
    return trace
