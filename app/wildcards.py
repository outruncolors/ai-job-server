"""Wildcard store — persists the unified Cruddable envelope.

On disk (``config/wildcards/index.json``) each item is an envelope:
``{schema_version,type:"wildcard",id,name,description,tags,created_at,updated_at,
data:{entries:[{text,weight?}]}}``. IDs are human-readable slugs. Legacy (pre-envelope)
docs are tolerated on read and reshaped via :func:`_normalize` (the one-time migration in
``app.cruddables.migrate`` does the authoritative re-slug + reference fixes).

Wildcards reference each other by **name** (``%%name%%``), not id, so re-slugging ids does
not affect references.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Optional

from app.cruddables.envelope import now_iso, slugify, unique_id

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DIR: Path = PROJECT_ROOT / "config" / "wildcards"
_INDEX_PATH: Path = _DIR / "index.json"

_TOKEN_RE = re.compile(r"%%([^%]+)%%")

TYPE_NAME = "wildcard"


def _read_index() -> list[dict]:
    if not _INDEX_PATH.exists():
        return []
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _normalize(doc: dict) -> dict:
    """Return ``doc`` as an envelope, reshaping a legacy flat wildcard if needed.

    Legacy docs keep their existing id here (the migration assigns unique slugs); this is
    only a defensive read-time fallback so nothing crashes before migration runs.
    """
    if doc.get("type") == TYPE_NAME and isinstance(doc.get("data"), dict):
        doc.setdefault("tags", [])
        doc.setdefault("description", "")
        return doc
    now = now_iso()
    return {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": doc.get("id") or slugify(doc.get("name") or "wildcard"),
        "name": doc.get("name") or "",
        "description": doc.get("description") or "",
        "tags": doc.get("tags") or [],
        "created_at": doc.get("created_at") or now,
        "updated_at": doc.get("updated_at") or now,
        "data": {"entries": doc.get("entries") or []},
    }


def _entries_of(doc: dict) -> list[dict]:
    return (doc.get("data") or {}).get("entries") or []


def _extract_refs(entries: list[dict]) -> list[str]:
    refs: list[str] = []
    for e in entries or []:
        for m in _TOKEN_RE.finditer(e.get("text") or ""):
            refs.append(m.group(1).lower())
    return refs


def check_for_cycles(items: list[dict], root_name: str) -> None:
    name_refs: dict[str, list[str]] = {}
    display: dict[str, str] = {}
    for it in items:
        key = (it.get("name") or "").lower()
        if not key:
            continue
        name_refs[key] = _extract_refs(_entries_of(it))
        display[key] = it.get("name") or key

    root = (root_name or "").lower()
    if root not in name_refs:
        return

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {k: WHITE for k in name_refs}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in name_refs.get(node, []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                cycle = [display[n] for n in path] + [display[dep]]
                raise ValueError(
                    "Cycle detected: " + " → ".join(f"%%{n}%%" for n in cycle)
                )
            if color[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        color[node] = BLACK

    dfs(root, [])


def _taken_ids(items: list[dict], *, exclude: Optional[str] = None) -> set[str]:
    return {it["id"] for it in items if it.get("id") and it["id"] != exclude}


def list_wildcards() -> list[dict]:
    return [_normalize(dict(it)) for it in _read_index()]


def get_wildcard(wid: str) -> Optional[dict]:
    return next((it for it in list_wildcards() if it["id"] == wid), None)


def create_wildcard(name: str, entries: list[dict], description: str = "") -> dict:
    if not name or not name.strip():
        raise ValueError("name is required")
    items = list_wildcards()
    now = now_iso()
    new_id = unique_id(slugify(name), _taken_ids(items))
    item = {
        "schema_version": 1,
        "type": TYPE_NAME,
        "id": new_id,
        "name": name,
        "description": description,
        "tags": [],
        "created_at": now,
        "updated_at": now,
        "data": {"entries": entries},
    }
    candidate = items + [item]
    check_for_cycles(candidate, name)
    _write_index(candidate)
    return item


def update_wildcard(
    wid: str, name: str, entries: list[dict], description: str = ""
) -> Optional[dict]:
    items = list_wildcards()
    idx = next((i for i, e in enumerate(items) if e["id"] == wid), None)
    if idx is None:
        return None
    item = dict(items[idx])
    item["name"] = name
    item["description"] = description
    item["data"] = {**(item.get("data") or {}), "entries": entries}
    item["updated_at"] = now_iso()
    candidate = list(items)
    candidate[idx] = item
    check_for_cycles(candidate, name)
    _write_index(candidate)
    return item


def delete_wildcard(wid: str) -> bool:
    items = list_wildcards()
    new_items = [e for e in items if e["id"] != wid]
    if len(new_items) == len(items):
        return False
    _write_index(new_items)
    return True


# --- resolution (server-side) ----------------------------------------------
# The frontend resolves %%name%% tokens before sending a prompt (static/js/
# wildcards.js). Prompts built on the server (e.g. Prattletale's turn prompt)
# never pass through it, so this is the equivalent server-side pass: weighted
# pick per token, nested refs, cycle-safe, depth-capped. Unknown tokens are left
# literal (same as the frontend). Default per-entry weight is 5, matching JS.

_WC_MAX_DEPTH = 16


def _pick_weighted(entries: list[dict]) -> str:
    texts = [e.get("text") or "" for e in entries]
    weights = [w if (w := e.get("weight")) else 5 for e in entries]  # 0/None -> 5, like JS `|| 5`
    if not texts:
        return ""
    total = sum(weights)
    if total <= 0:
        return random.choice(texts)
    return random.choices(texts, weights=weights, k=1)[0]


def _resolve(text: str, by_name: dict[str, dict], visiting: set[str], depth: int) -> str:
    if not text or "%%" not in text or depth >= _WC_MAX_DEPTH:
        return text

    def repl(m: "re.Match[str]") -> str:
        key = m.group(1).lower()
        wc = by_name.get(key)
        entries = _entries_of(wc) if wc else []
        if not entries or key in visiting:
            return m.group(0)  # unknown or cyclic -> leave the token literal
        picked = _pick_weighted(entries)
        return _resolve(picked, by_name, visiting | {key}, depth + 1)

    return _TOKEN_RE.sub(repl, text)


def resolve_wildcards(text: str) -> str:
    """Resolve ``%%name%%`` wildcard tokens in ``text`` with a weighted random
    pick per token (recursively, cycle-safe). Unknown tokens are left literal.
    A fresh pick is made on every call (so each turn varies)."""
    if not text or "%%" not in text:
        return text
    by_name = {(it.get("name") or "").lower(): it for it in list_wildcards()}
    return _resolve(text, by_name, set(), 0)


def upsert_envelope(env: dict) -> tuple[str, str]:
    """Write an envelope dict with its explicit ``id`` (create or overwrite). Used by
    packs/extend. Returns ``("created"|"updated", id)``."""
    items = list_wildcards()
    idx = next((i for i, e in enumerate(items) if e["id"] == env["id"]), None)
    now = now_iso()
    doc = _normalize(dict(env))
    if idx is None:
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        items.append(doc)
        action = "created"
    else:
        doc["created_at"] = items[idx].get("created_at") or now
        doc["updated_at"] = now
        items[idx] = doc
        action = "updated"
    check_for_cycles(items, doc.get("name") or "")
    _write_index(items)
    return action, doc["id"]
