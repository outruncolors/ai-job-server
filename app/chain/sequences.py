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


def check_for_cycles(entries: list[dict], root_id: str) -> None:
    seq_map = {s["id"]: s for s in entries}

    def direct_deps(sid: str) -> list[str]:
        seq = seq_map.get(sid)
        if not seq:
            return []
        return [
            step["sequence_id"]
            for step in seq.get("steps", [])
            if step.get("type") == "sequence" and step.get("sequence_id")
        ]

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {sid: WHITE for sid in seq_map}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in direct_deps(node):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                cycle_names = [seq_map[n]["name"] for n in path] + [seq_map[dep]["name"]]
                raise ValueError("Cycle detected: " + " → ".join(cycle_names))
            if color[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        color[node] = BLACK

    if root_id in color:
        dfs(root_id, [])


def validate_llm_step_capabilities(steps: list[dict]) -> None:
    """For each LLM step that declares `requires`, ensure the chosen (or default)
    preset advertises every required capability. Raises ValueError on mismatch.
    """
    from .. import llm_presets
    from ..llamacpp.config import get_config as llamacpp_get_config

    default_name: Optional[str] = None
    for idx, step in enumerate(steps, start=1):
        if step.get("type") != "llm":
            continue
        requires = list(step.get("requires") or [])
        if not requires:
            continue
        preset_name = step.get("preset") or default_name
        if not preset_name:
            # Lazily read the default only when needed.
            default_name = default_name or llamacpp_get_config().default_preset
            preset_name = step.get("preset") or default_name
        if not preset_name:
            raise ValueError(
                f"Step {idx} ({step.get('name') or '?'}): requires={requires} but no preset is selected "
                f"and no default_preset is configured in llamacpp.json"
            )
        preset = llm_presets.get_preset(preset_name)
        if preset is None:
            raise ValueError(
                f"Step {idx} ({step.get('name') or '?'}): references unknown LLM preset {preset_name!r}"
            )
        caps = set(preset.get("capabilities") or [])
        missing = [c for c in requires if c not in caps]
        if missing:
            raise ValueError(
                f"Step {idx} ({step.get('name') or '?'}): preset {preset_name!r} is missing required "
                f"capabilities {missing} (preset has {sorted(caps)})"
            )


def save_sequence(name: str, steps: list[dict]) -> dict:
    validate_llm_step_capabilities(steps)
    entries = _read_index()
    existing = next((e for e in entries if e["name"] == name), None)
    now = _now_iso()
    if existing:
        existing["steps"] = steps
        existing["updated_at"] = now
        check_for_cycles(entries, existing["id"])
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
    check_for_cycles(entries, entry["id"])
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
