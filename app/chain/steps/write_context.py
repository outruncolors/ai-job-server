from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run_write_context_step(
    step_dir: Path,
    step: Any,
    text_output: str,
) -> str:
    """Execute a write_context step. Returns the output filename."""
    from ..context_library import create_item, list_items, update_item

    parts = [p for p in [step.ctx_pre, text_output, step.ctx_post] if p]
    entry = "\n\n".join(parts)

    existing = next((item for item in list_items() if item["title"] == step.ctx_name), None)
    if existing:
        if step.ctx_overwrite:
            new_content = entry
        else:
            new_content = existing["content"] + "\n\n---\n\n" + entry
        result_item = update_item(existing["id"], content=new_content)
    else:
        result_item = create_item(
            title=step.ctx_name or "",
            tags=step.ctx_tags or [],
            description=step.ctx_description or "",
            content=entry,
        )

    (step_dir / "output.json").write_text(
        json.dumps(result_item, indent=2), encoding="utf-8"
    )
    return "output.json"
