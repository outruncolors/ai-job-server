from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEQUENCES_DIR: Path = PROJECT_ROOT / "config" / "chain_sequences"
INDEX_PATH: Path = SEQUENCES_DIR / "index.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _unique_name(base: str, existing: list[str]) -> str:
    if base not in existing:
        return base
    n = 2
    while f"{base} ({n})" in existing:
        n += 1
    return f"{base} ({n})"


def list_sequences() -> list[dict]:
    return _read_index()


def save_sequence(name: str, steps: list[dict]) -> dict:
    entries = _read_index()
    existing = next((e for e in entries if e["name"] == name), None)
    now = _now_iso()
    if existing:
        existing["steps"] = steps
        existing["updated_at"] = now
        _write_index(entries)
        return existing
    entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "steps": steps,
        "created_at": now,
        "updated_at": now,
    }
    entries.append(entry)
    _write_index(entries)
    return entry


def delete_sequence(seq_id: str) -> bool:
    entries = _read_index()
    new_entries = [e for e in entries if e["id"] != seq_id]
    if len(new_entries) == len(entries):
        return False
    _write_index(new_entries)
    return True


def duplicate_sequence(seq_id: str) -> Optional[dict]:
    entries = _read_index()
    source = next((e for e in entries if e["id"] == seq_id), None)
    if source is None:
        return None
    existing_names = [e["name"] for e in entries]
    new_name = _unique_name(source["name"] + " (copy)", existing_names)
    now = _now_iso()
    entry = {
        "id": str(uuid.uuid4()),
        "name": new_name,
        "steps": source["steps"],
        "created_at": now,
        "updated_at": now,
    }
    entries.append(entry)
    _write_index(entries)
    return entry
