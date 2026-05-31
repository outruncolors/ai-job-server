from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run_save_wildcard_step(
    step_dir: Path,
    step: Any,
    alt: Any,
    rendered_name: str,
    rendered_prompt: str,
    text_output: str,
) -> str:
    """Create or append to a wildcard. Returns the output filename.

    Content priority: rendered alternative `prompt` → `text_output`.
    """
    from ...wildcards import create_wildcard, list_wildcards, update_wildcard

    name = (rendered_name or "").strip()
    if not name:
        raise RuntimeError("save_wildcard step requires wildcard_name (after template rendering)")
    body = rendered_prompt.strip() or text_output.strip()
    if not body:
        raise RuntimeError("save_wildcard step has no value (rendered prompt and text_output both empty)")

    mode = alt.wildcard_mode or "append"
    new_entry = {"text": body}

    if mode == "create":
        result = create_wildcard(name, [new_entry], "")
        action = "create"
    else:
        existing = next((w for w in list_wildcards() if w.get("name") == name), None)
        if existing is None:
            result = create_wildcard(name, [new_entry], "")
            action = "create_missing"
        else:
            merged_entries = list((existing.get("data") or {}).get("entries") or []) + [new_entry]
            result = update_wildcard(
                existing["id"],
                existing["name"],
                merged_entries,
                existing.get("description") or "",
            )
            action = "append"

    payload = {"action": action, "wildcard": result, "entry": new_entry}
    (step_dir / "output.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return "output.json"
