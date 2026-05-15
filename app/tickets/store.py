from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TICKETS_DIR: Path = PROJECT_ROOT / "config" / "tickets"
INDEX_PATH: Path = TICKETS_DIR / "index.json"

VALID_STATUSES = {"todo", "in-progress", "done"}
ALLOWED_FIELDS = {"title", "description", "status", "file_hints", "branch", "priority"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _sorted(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e.get("priority", 1_000_000), e.get("created_at", "")))


def list_tickets() -> list[dict]:
    return _sorted(_read_index())


def get_ticket(tid: str) -> Optional[dict]:
    return next((e for e in _read_index() if e["id"] == tid), None)


def create_ticket(
    title: str,
    description: str = "",
    file_hints: Optional[list[str]] = None,
) -> dict:
    if not title or not title.strip():
        raise ValueError("title is required")
    entries = _read_index()
    now = _now_iso()
    entry = {
        "id": str(uuid.uuid4()),
        "title": title.strip(),
        "description": description or "",
        "priority": len(entries),
        "status": "todo",
        "file_hints": list(file_hints or []),
        "branch": None,
        "created_at": now,
        "updated_at": now,
    }
    entries.append(entry)
    _write_index(entries)
    return entry


def update_ticket(tid: str, **fields) -> Optional[dict]:
    entries = _read_index()
    entry = next((e for e in entries if e["id"] == tid), None)
    if entry is None:
        return None
    for k, v in fields.items():
        if k not in ALLOWED_FIELDS:
            continue
        if k == "status" and v not in VALID_STATUSES:
            raise ValueError(f"invalid status: {v}")
        if k == "file_hints" and v is not None and not isinstance(v, list):
            raise ValueError("file_hints must be a list")
        entry[k] = v
    entry["updated_at"] = _now_iso()
    _write_index(entries)
    return entry


def delete_ticket(tid: str) -> bool:
    entries = _read_index()
    new_entries = [e for e in entries if e["id"] != tid]
    if len(new_entries) == len(entries):
        return False
    for i, e in enumerate(_sorted(new_entries)):
        e["priority"] = i
    _write_index(new_entries)
    return True


def reorder_tickets(ids: list[str]) -> list[dict]:
    entries = _read_index()
    existing_ids = {e["id"] for e in entries}
    given_ids = set(ids)
    if given_ids != existing_ids:
        missing = existing_ids - given_ids
        extra = given_ids - existing_ids
        raise ValueError(
            f"reorder id set mismatch (missing={sorted(missing)}, extra={sorted(extra)})"
        )
    pos = {tid: i for i, tid in enumerate(ids)}
    now = _now_iso()
    for e in entries:
        new_priority = pos[e["id"]]
        if e.get("priority") != new_priority:
            e["priority"] = new_priority
            e["updated_at"] = now
    _write_index(entries)
    return _sorted(entries)


def next_ticket() -> Optional[dict]:
    for e in _sorted(_read_index()):
        if e.get("status") == "todo":
            return e
    return None
