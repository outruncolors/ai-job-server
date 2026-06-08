"""Tale-scoped, file-first persistence for Tomeberry.

Layout (gitignored under ``config/tomeberry/``)::

    tales/<tale_id>/
      tale.json
      concepts/<concept_id>.json
      hierarchy.json                 # denormalized structural tree (rebuildable)
      assistant/<thread_id>.json     # assistant-pane message log
      traces/<request_id>.json       # rich per-request debug record
      workspace/                     # the MCP filesystem sandbox root for this tale

Atomic ``tmp + os.replace`` writes (copied from prattletale's store). Concepts are
intrinsically per-tale; cruddables/Packs stay server-wide globals (B8).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import (
    Concept,
    ConceptClass,
    ConceptMetadata,
    HistoryEntry,
    Link,
    Tale,
    TaleSettings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TOMEBERRY_DIR: Path = PROJECT_ROOT / "config" / "tomeberry"


def _tales_dir() -> Path:
    return TOMEBERRY_DIR / "tales"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    s = _SLUG_RE.sub("_", (text or "").lower()).strip("_")
    return s or "x"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---- paths -----------------------------------------------------------------


def tale_dir(tale_id: str) -> Path:
    return _tales_dir() / tale_id


def _tale_file(tale_id: str) -> Path:
    return tale_dir(tale_id) / "tale.json"


def _concepts_dir(tale_id: str) -> Path:
    return tale_dir(tale_id) / "concepts"


def _concept_file(tale_id: str, cid: str) -> Path:
    return _concepts_dir(tale_id) / f"{cid}.json"


def workspace_dir(tale_id: str) -> Path:
    return tale_dir(tale_id) / "workspace"


# ---- tales -----------------------------------------------------------------


def _new_id(prefix: str, hint: str = "") -> str:
    suffix = uuid.uuid4().hex[:6]
    return f"{prefix}_{_slug(hint)}_{suffix}" if hint else f"{prefix}_{suffix}"


def create_tale(fields: dict) -> dict:
    title = (fields.get("title") or "Untitled Tale").strip()
    tale_id = _new_id("tale", title)
    d = tale_dir(tale_id)
    (d / "concepts").mkdir(parents=True, exist_ok=True)
    (d / "assistant").mkdir(parents=True, exist_ok=True)
    (d / "traces").mkdir(parents=True, exist_ok=True)
    workspace_dir(tale_id).mkdir(parents=True, exist_ok=True)

    now = _now()
    # Root structural unit (type "tale") — the manuscript tree's root.
    root = Concept(
        id=_new_id("concept_tale", title),
        concept_class=ConceptClass.structural_unit,
        type="tale",
        title=title,
        created_at=now,
        updated_at=now,
    )
    _atomic_write(_concept_file(tale_id, root.id), root.model_dump(mode="json"))

    # Premise narrative construct.
    premise = Concept(
        id=_new_id("concept_premise"),
        concept_class=ConceptClass.narrative_construct,
        type="premise",
        title="Premise",
        body=(fields.get("premise") or "").strip(),
        created_at=now,
        updated_at=now,
    )
    _atomic_write(_concept_file(tale_id, premise.id), premise.model_dump(mode="json"))

    tale = Tale(
        id=tale_id,
        title=title,
        premise_id=premise.id,
        structural_root_id=root.id,
        default_mode=fields.get("default_mode") or "draft",
        settings=TaleSettings(workspace_dir=str(workspace_dir(tale_id))),
        created_at=now,
        updated_at=now,
    )
    _atomic_write(_tale_file(tale_id), tale.model_dump(mode="json"))
    rebuild_hierarchy(tale_id)
    return tale.model_dump(mode="json")


def list_tales() -> list[dict]:
    base = _tales_dir()
    if not base.is_dir():
        return []
    out: list[dict] = []
    for d in sorted(base.iterdir()):
        f = d / "tale.json"
        if f.exists():
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    out.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
    return out


def get_tale(tale_id: str) -> Optional[dict]:
    f = _tale_file(tale_id)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def update_tale(tale_id: str, patch: dict) -> Optional[dict]:
    tale = get_tale(tale_id)
    if tale is None:
        return None
    for k in ("title", "default_mode", "default_saved_prompt"):
        if patch.get(k) is not None:
            tale[k] = patch[k]
    if patch.get("settings") is not None:
        tale["settings"] = {**tale.get("settings", {}), **patch["settings"]}
    tale["updated_at"] = _now()
    _atomic_write(_tale_file(tale_id), tale)
    return tale


def delete_tale(tale_id: str) -> bool:
    import shutil

    d = tale_dir(tale_id)
    if not d.is_dir():
        return False
    shutil.rmtree(d)
    return True


def touch_tale(tale_id: str) -> None:
    tale = get_tale(tale_id)
    if tale is not None:
        tale["updated_at"] = _now()
        _atomic_write(_tale_file(tale_id), tale)


# ---- concepts --------------------------------------------------------------


def list_concepts(
    tale_id: str,
    concept_class: Optional[str] = None,
    type_: Optional[str] = None,
) -> list[dict]:
    d = _concepts_dir(tale_id)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for f in d.glob("*.json"):
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if concept_class and c.get("concept_class") != concept_class:
            continue
        if type_ and c.get("type") != type_:
            continue
        out.append(c)
    out.sort(key=lambda c: (c.get("order", 0), c.get("created_at", "")))
    return out


def get_concept(tale_id: str, cid: str) -> Optional[dict]:
    f = _concept_file(tale_id, cid)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def create_concept(tale_id: str, fields: dict) -> Optional[dict]:
    if get_tale(tale_id) is None:
        return None
    now = _now()
    ctype = fields.get("type") or "scene"
    cid = _new_id(f"concept_{_slug(ctype)}")
    concept = Concept(
        id=cid,
        concept_class=ConceptClass(fields["concept_class"]),
        type=ctype,
        title=(fields.get("title") or "").strip(),
        body=fields.get("body") or "",
        parent_id=fields.get("parent_id"),
        order=fields.get("order") if fields.get("order") is not None else _next_order(tale_id, fields.get("parent_id")),
        links=[Link(**l) for l in (fields.get("links") or [])],
        metadata=ConceptMetadata(**(fields.get("metadata") or {})),
        history=[HistoryEntry(at=now, kind="manual_edit", summary="created")],
        created_at=now,
        updated_at=now,
    )
    concept.metadata.word_count = len((concept.body or "").split())
    _atomic_write(_concept_file(tale_id, cid), concept.model_dump(mode="json"))
    if concept.concept_class == ConceptClass.structural_unit:
        rebuild_hierarchy(tale_id)
    touch_tale(tale_id)
    return concept.model_dump(mode="json")


def _next_order(tale_id: str, parent_id: Optional[str]) -> int:
    sibs = [c for c in list_concepts(tale_id) if c.get("parent_id") == parent_id]
    return max((c.get("order", 0) for c in sibs), default=-1) + 1


def update_concept(
    tale_id: str,
    cid: str,
    patch: dict,
    *,
    history: Optional[HistoryEntry] = None,
) -> Optional[dict]:
    concept = get_concept(tale_id, cid)
    if concept is None:
        return None
    for k in ("title", "body", "type"):
        if patch.get(k) is not None:
            concept[k] = patch[k]
    if patch.get("order") is not None:
        concept["order"] = patch["order"]
    if patch.get("metadata") is not None:
        concept["metadata"] = {**concept.get("metadata", {}), **patch["metadata"]}
    if "body" in patch and patch["body"] is not None:
        concept["metadata"]["word_count"] = len((patch["body"] or "").split())
    if history is not None:
        concept.setdefault("history", []).append(history.model_dump(mode="json"))
    concept["updated_at"] = _now()
    _atomic_write(_concept_file(tale_id, cid), concept)
    touch_tale(tale_id)
    return concept


def delete_concept(tale_id: str, cid: str) -> bool:
    f = _concept_file(tale_id, cid)
    if not f.exists():
        return False
    was_su = (get_concept(tale_id, cid) or {}).get("concept_class") == "structural_unit"
    f.unlink()
    # Drop dangling links pointing at the deleted concept.
    for c in list_concepts(tale_id):
        links = c.get("links") or []
        kept = [l for l in links if l.get("target_id") != cid]
        if len(kept) != len(links):
            c["links"] = kept
            _atomic_write(_concept_file(tale_id, c["id"]), c)
    if was_su:
        rebuild_hierarchy(tale_id)
    touch_tale(tale_id)
    return True


def move_concept(tale_id: str, cid: str, parent_id: Optional[str], order: int) -> Optional[dict]:
    concept = get_concept(tale_id, cid)
    if concept is None:
        return None
    concept["parent_id"] = parent_id
    concept["order"] = order
    concept["updated_at"] = _now()
    _atomic_write(_concept_file(tale_id, cid), concept)
    rebuild_hierarchy(tale_id)
    touch_tale(tale_id)
    return concept


def add_link(tale_id: str, cid: str, link: dict) -> Optional[dict]:
    concept = get_concept(tale_id, cid)
    if concept is None:
        return None
    links = concept.get("links") or []
    # de-dup on (rel, target_id)
    links = [l for l in links if not (l.get("rel") == link["rel"] and l.get("target_id") == link["target_id"])]
    links.append(Link(**link).model_dump(mode="json"))
    concept["links"] = links
    concept["updated_at"] = _now()
    _atomic_write(_concept_file(tale_id, cid), concept)
    touch_tale(tale_id)
    return concept


def remove_link(tale_id: str, cid: str, rel: str, target_id: str) -> Optional[dict]:
    concept = get_concept(tale_id, cid)
    if concept is None:
        return None
    links = concept.get("links") or []
    concept["links"] = [
        l for l in links if not (l.get("rel") == rel and l.get("target_id") == target_id)
    ]
    concept["updated_at"] = _now()
    _atomic_write(_concept_file(tale_id, cid), concept)
    touch_tale(tale_id)
    return concept


# ---- hierarchy -------------------------------------------------------------


def rebuild_hierarchy(tale_id: str) -> dict:
    """Recompute the structural tree from concepts' parent_id/order and cache it."""
    tale = get_tale(tale_id)
    root_id = tale.get("structural_root_id") if tale else None
    sus = [c for c in list_concepts(tale_id, concept_class="structural_unit")]
    by_parent: dict[Optional[str], list[dict]] = {}
    for c in sus:
        by_parent.setdefault(c.get("parent_id"), []).append(c)
    for kids in by_parent.values():
        kids.sort(key=lambda c: (c.get("order", 0), c.get("created_at", "")))

    def node(c: dict) -> dict:
        return {
            "id": c["id"],
            "type": c.get("type"),
            "title": c.get("title", ""),
            "order": c.get("order", 0),
            "word_count": (c.get("metadata") or {}).get("word_count", 0),
            "status": (c.get("metadata") or {}).get("status", "draft"),
            "children": [node(k) for k in by_parent.get(c["id"], [])],
        }

    roots = by_parent.get(root_id, []) if root_id else by_parent.get(None, [])
    root_concept = get_concept(tale_id, root_id) if root_id else None
    tree = {
        "root": node(root_concept) if root_concept else None,
        "orphans": [node(c) for c in by_parent.get(None, []) if c.get("id") != root_id]
        if root_id
        else [],
        "updated_at": _now(),
    }
    # When the root has no children recorded under its id but units exist under
    # None, surface them as the root's children (fresh tale convenience).
    if tree["root"] is not None and not tree["root"]["children"]:
        tree["root"]["children"] = [
            node(c) for c in by_parent.get(None, []) if c.get("id") != root_id
        ]
        tree["orphans"] = []
    _atomic_write(tale_dir(tale_id) / "hierarchy.json", tree)
    return tree


def get_hierarchy(tale_id: str) -> Optional[dict]:
    f = tale_dir(tale_id) / "hierarchy.json"
    if not f.exists():
        if get_tale(tale_id) is None:
            return None
        return rebuild_hierarchy(tale_id)
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return rebuild_hierarchy(tale_id)


# ---- assistant pane --------------------------------------------------------


def _assistant_file(tale_id: str, thread_id: str) -> Path:
    return tale_dir(tale_id) / "assistant" / f"{thread_id}.json"


def get_assistant(tale_id: str, thread_id: str = "main") -> dict:
    f = _assistant_file(tale_id, thread_id)
    if not f.exists():
        return {"thread_id": thread_id, "messages": []}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"thread_id": thread_id, "messages": []}


def append_assistant_message(tale_id: str, msg: dict, thread_id: str = "main") -> dict:
    thread = get_assistant(tale_id, thread_id)
    thread["messages"].append(msg)
    _atomic_write(_assistant_file(tale_id, thread_id), thread)
    return msg


def update_assistant_message(
    tale_id: str, msg_id: str, patch: dict, thread_id: str = "main"
) -> Optional[dict]:
    thread = get_assistant(tale_id, thread_id)
    found = None
    for m in thread["messages"]:
        if m.get("id") == msg_id:
            m.update(patch)
            found = m
            break
    if found is None:
        return None
    _atomic_write(_assistant_file(tale_id, thread_id), thread)
    return found


def new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:8]}"


def find_request_message(
    tale_id: str, request_id: str, kind: Optional[str] = "proposal", thread_id: str = "main"
) -> Optional[dict]:
    thread = get_assistant(tale_id, thread_id)
    for m in thread["messages"]:
        if m.get("request_id") == request_id and (kind is None or m.get("kind") == kind):
            return m
    return None


def set_proposal_status(
    tale_id: str, request_id: str, status: str, thread_id: str = "main"
) -> Optional[dict]:
    """Set the proposal status on every proposal message of ``request_id``."""
    thread = get_assistant(tale_id, thread_id)
    found = None
    for m in thread["messages"]:
        if m.get("request_id") == request_id and m.get("proposal"):
            m["proposal"]["status"] = status
            found = m
    if found is not None:
        _atomic_write(_assistant_file(tale_id, thread_id), thread)
    return found


# ---- traces ----------------------------------------------------------------


def _traces_dir(tale_id: str) -> Path:
    return tale_dir(tale_id) / "traces"


def write_trace(tale_id: str, request_id: str, trace: dict) -> None:
    _atomic_write(_traces_dir(tale_id) / f"{request_id}.json", trace)


def get_trace(tale_id: str, request_id: str) -> Optional[dict]:
    f = _traces_dir(tale_id) / f"{request_id}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_traces(tale_id: str) -> list[dict]:
    d = _traces_dir(tale_id)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for f in d.glob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append(
            {
                "request_id": t.get("request_id", f.stem),
                "at": t.get("at"),
                "mode": t.get("mode"),
                "user_action": t.get("user_action"),
                "error": t.get("error"),
            }
        )
    out.sort(key=lambda t: t.get("at") or "", reverse=True)
    return out


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:8]}"


# ---- templates + export ----------------------------------------------------


def apply_template(tale_id: str, template_data: dict) -> Optional[dict]:
    """Copy a template's concept records into the tale. Returns {created: [ids]}."""
    tale = get_tale(tale_id)
    if tale is None:
        return None
    root_id = tale.get("structural_root_id")
    ref_map: dict[str, str] = {}
    created: list[str] = []
    for rec in template_data.get("concepts", []):
        parent_ref = rec.get("parent_ref")
        if parent_ref in (None, "", "root"):
            parent_id = root_id if rec.get("concept_class") == "structural_unit" else None
        else:
            parent_id = ref_map.get(parent_ref)
        c = create_concept(
            tale_id,
            {
                "concept_class": rec.get("concept_class", "structural_unit"),
                "type": rec.get("type") or "scene",
                "title": rec.get("title") or "",
                "body": rec.get("body") or "",
                "parent_id": parent_id,
                "order": rec.get("order"),
                "links": rec.get("links") or [],
            },
        )
        if c:
            created.append(c["id"])
            if rec.get("ref"):
                ref_map[rec["ref"]] = c["id"]
    rebuild_hierarchy(tale_id)
    return {"created": created}


def export_tale(tale_id: str) -> Optional[dict]:
    """Bundle the whole tale (tale + concepts + hierarchy + assistant + traces)."""
    tale = get_tale(tale_id)
    if tale is None:
        return None
    traces = [get_trace(tale_id, t["request_id"]) for t in list_traces(tale_id)]
    return {
        "schema_version": 1,
        "exported_at": _now(),
        "tale": tale,
        "concepts": list_concepts(tale_id),
        "hierarchy": get_hierarchy(tale_id),
        "assistant": get_assistant(tale_id),
        "traces": [t for t in traces if t is not None],
    }
