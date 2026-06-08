from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run_write_context_step(
    step_dir: Path,
    step: Any,
    alt: Any,
    text_output: str,
    ctx_pre: str | None = None,
    ctx_post: str | None = None,
) -> str:
    """Execute a write_context step. Returns the output filename.

    ``ctx_pre`` / ``ctx_post`` are the template-rendered wrap-around text (resolved
    by the executor via the unified engine); they fall back to the raw alternative
    fields when omitted.
    """
    from ..context_library import create_item, list_items, update_item

    pre = ctx_pre if ctx_pre is not None else alt.ctx_pre
    post = ctx_post if ctx_post is not None else alt.ctx_post
    parts = [p for p in [pre, text_output, post] if p]
    entry = "\n\n".join(parts)

    existing = next((item for item in list_items() if item["title"] == alt.ctx_name), None)
    if existing:
        if alt.ctx_overwrite:
            new_content = entry
        else:
            new_content = existing["content"] + "\n\n---\n\n" + entry
        result_item = update_item(existing["id"], content=new_content)
    else:
        result_item = create_item(
            title=alt.ctx_name or "",
            tags=alt.ctx_tags or [],
            description=alt.ctx_description or "",
            content=entry,
        )

    (step_dir / "output.json").write_text(
        json.dumps(result_item, indent=2), encoding="utf-8"
    )
    return "output.json"
