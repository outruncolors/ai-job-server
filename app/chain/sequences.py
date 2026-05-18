from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEQUENCES_DIR: Path = PROJECT_ROOT / "config" / "chain_sequences"
INDEX_PATH: Path = SEQUENCES_DIR / "index.json"

SCHEMA_VERSION = 2


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
    """DFS cycle detection over `type=sequence` step references between top-level sequences."""
    seq_map = {s["id"]: s for s in entries}

    def direct_deps(sid: str) -> list[str]:
        seq = seq_map.get(sid)
        if not seq:
            return []
        deps: list[str] = []
        for step in seq.get("steps", []):
            if step.get("type") != "sequence":
                continue
            # v2: sequence_id may live on an alternative
            for alt in step.get("alternatives") or []:
                if alt.get("sequence_id"):
                    deps.append(alt["sequence_id"])
            # legacy/shorthand: sequence_id on the step itself
            if step.get("sequence_id"):
                deps.append(step["sequence_id"])
        return deps

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


def _normalize_step(step: dict, position: int) -> dict:
    """Ensure a step dict carries `number`, `alternatives` (non-empty), and a valid `type`."""
    step = dict(step)
    if "number" not in step or not isinstance(step.get("number"), int) or step["number"] <= 0:
        step["number"] = position
    step.setdefault("type", "llm")
    step.setdefault("visit_cap", 100)
    alts = step.get("alternatives")
    if not alts:
        # Hoist v1 shorthand fields into a single alternative for persistence.
        from .models import _ALTERNATIVE_FIELDS

        hoisted = {k: step.pop(k) for k in list(step.keys()) if k in _ALTERNATIVE_FIELDS}
        step["alternatives"] = [hoisted] if hoisted else [{}]
    return step


def _validate_steps(steps: list[dict]) -> None:
    """Pre-save structural validation for v2 sequences."""
    numbers: set[int] = set()
    for idx, step in enumerate(steps, start=1):
        n = step.get("number")
        if not isinstance(n, int) or n <= 0:
            raise ValueError(f"Step at position {idx} is missing a positive integer 'number'")
        if n in numbers:
            raise ValueError(f"Duplicate step number {n} — each step must have a unique number")
        numbers.add(n)

    for idx, step in enumerate(steps, start=1):
        alts = step.get("alternatives") or []
        if not alts:
            raise ValueError(f"Step {step.get('number') or idx}: must have at least one alternative")
        for ai, alt in enumerate(alts, start=1):
            w = alt.get("weight", 1)
            if not isinstance(w, int) or w < 1:
                raise ValueError(
                    f"Step {step.get('number') or idx} alternative {ai}: weight must be a positive integer"
                )

        if step.get("type") == "goto":
            for ai, alt in enumerate(alts, start=1):
                has_target = alt.get("target_step") is not None
                fall_through = bool(alt.get("fall_through"))
                if has_target == fall_through:
                    raise ValueError(
                        f"Step {step.get('number') or idx} goto alternative {ai}: "
                        "exactly one of target_step or fall_through must be set"
                    )
                if has_target and alt["target_step"] not in numbers:
                    raise ValueError(
                        f"Step {step.get('number') or idx} goto alternative {ai}: "
                        f"target_step {alt['target_step']} does not exist in this sequence"
                    )


def validate_llm_step_capabilities(steps: list[dict]) -> None:
    """For each LLM alternative that declares `requires`, ensure the chosen (or default)
    preset advertises every required capability. Raises ValueError on mismatch.
    """
    from .. import llm_presets
    from ..llamacpp.config import get_config as llamacpp_get_config

    default_name: Optional[str] = None
    for idx, step in enumerate(steps, start=1):
        if step.get("type") != "llm":
            continue
        for ai, alt in enumerate(step.get("alternatives") or [], start=1):
            requires = list(alt.get("requires") or [])
            if not requires:
                continue
            preset_name = alt.get("preset") or default_name
            if not preset_name:
                default_name = default_name or llamacpp_get_config().default_preset
                preset_name = alt.get("preset") or default_name
            if not preset_name:
                raise ValueError(
                    f"Step {step.get('number') or idx} alt {ai} ({step.get('name') or '?'}): "
                    f"requires={requires} but no preset is selected and no default_preset is configured"
                )
            preset = llm_presets.get_preset(preset_name)
            if preset is None:
                raise ValueError(
                    f"Step {step.get('number') or idx} alt {ai} ({step.get('name') or '?'}): "
                    f"references unknown LLM preset {preset_name!r}"
                )
            caps = set(preset.get("capabilities") or [])
            missing = [c for c in requires if c not in caps]
            if missing:
                raise ValueError(
                    f"Step {step.get('number') or idx} alt {ai} ({step.get('name') or '?'}): "
                    f"preset {preset_name!r} is missing required capabilities {missing} "
                    f"(preset has {sorted(caps)})"
                )


def save_sequence(
    name: str,
    steps: list[dict],
    *,
    variables: Optional[list[dict]] = None,
) -> dict:
    normalized = [_normalize_step(s, i + 1) for i, s in enumerate(steps)]
    _validate_steps(normalized)
    validate_llm_step_capabilities(normalized)
    vars_list = list(variables or [])
    entries = _read_index()
    existing = next((e for e in entries if e["name"] == name), None)
    now = _now_iso()
    if existing:
        existing["schema_version"] = SCHEMA_VERSION
        existing["steps"] = normalized
        existing["variables"] = vars_list
        existing["updated_at"] = now
        check_for_cycles(entries, existing["id"])
        _write_index(entries)
        return existing
    entry = {
        "id": str(uuid.uuid4()),
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "steps": normalized,
        "variables": vars_list,
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
        "schema_version": source.get("schema_version", SCHEMA_VERSION),
        "name": new_name,
        "steps": source["steps"],
        "variables": list(source.get("variables") or []),
        "created_at": now,
        "updated_at": now,
    }
    entries.append(entry)
    _write_index(entries)
    return entry
