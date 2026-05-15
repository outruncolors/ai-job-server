from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR: Path = PROJECT_ROOT / "config" / "image_prompts"
INDEX_PATH: Path = PROMPTS_DIR / "index.json"

ALLOWED_UPDATE_FIELDS = {"name", "prompt", "workflow"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _unique_name(base_name: str, existing_names: list[str]) -> str:
    if base_name not in existing_names:
        return base_name
    n = 2
    while f"{base_name} ({n})" in existing_names:
        n += 1
    return f"{base_name} ({n})"


def list_prompts() -> list[dict]:
    return _read_index()


def get_prompt(prompt_id: str) -> Optional[dict]:
    return next((e for e in _read_index() if e["id"] == prompt_id), None)


def create_prompt(name: str, prompt: str, workflow: Optional[str] = None) -> dict:
    if not name or not name.strip():
        raise ValueError("name is required")
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")
    entries = _read_index()
    existing_names = [e["name"] for e in entries]
    final_name = _unique_name(name.strip(), existing_names)
    now = _now_iso()
    entry = {
        "id": str(uuid.uuid4()),
        "name": final_name,
        "prompt": prompt,
        "workflow": workflow,
        "created_at": now,
        "updated_at": now,
    }
    entries.append(entry)
    _write_index(entries)
    return entry


def update_prompt(prompt_id: str, **fields) -> Optional[dict]:
    entries = _read_index()
    entry = next((e for e in entries if e["id"] == prompt_id), None)
    if entry is None:
        return None
    for k, v in fields.items():
        if k not in ALLOWED_UPDATE_FIELDS:
            continue
        if k == "name":
            if not v or not str(v).strip():
                raise ValueError("name is required")
            new_name = str(v).strip()
            other_names = [e["name"] for e in entries if e["id"] != prompt_id]
            entry["name"] = _unique_name(new_name, other_names)
        else:
            entry[k] = v
    entry["updated_at"] = _now_iso()
    _write_index(entries)
    return entry


def delete_prompt(prompt_id: str) -> bool:
    entries = _read_index()
    new_entries = [e for e in entries if e["id"] != prompt_id]
    if len(new_entries) == len(entries):
        return False
    _write_index(new_entries)
    return True
