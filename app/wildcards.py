from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DIR: Path = PROJECT_ROOT / "config" / "wildcards"
_INDEX_PATH: Path = _DIR / "index.json"

_TOKEN_RE = re.compile(r"%%([^%]+)%%")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not _INDEX_PATH.exists():
        return []
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


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
        name_refs[key] = _extract_refs(it.get("entries") or [])
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


def list_wildcards() -> list[dict]:
    items = _read_index()
    for item in items:
        item.setdefault("description", "")
    return items


def create_wildcard(name: str, entries: list[dict], description: str = "") -> dict:
    items = _read_index()
    now = _now_iso()
    item = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "entries": entries,
        "created_at": now,
        "updated_at": now,
    }
    candidate = items + [item]
    check_for_cycles(candidate, name)
    _write_index(candidate)
    return item


def update_wildcard(
    wid: str, name: str, entries: list[dict], description: str = ""
) -> Optional[dict]:
    items = _read_index()
    idx = next((i for i, e in enumerate(items) if e["id"] == wid), None)
    if idx is None:
        return None
    item = dict(items[idx])
    item["name"] = name
    item["description"] = description
    item["entries"] = entries
    item["updated_at"] = _now_iso()
    candidate = list(items)
    candidate[idx] = item
    check_for_cycles(candidate, name)
    items[idx] = item
    _write_index(items)
    return item


def delete_wildcard(wid: str) -> bool:
    items = _read_index()
    new_items = [e for e in items if e["id"] != wid]
    if len(new_items) == len(items):
        return False
    _write_index(new_items)
    return True
