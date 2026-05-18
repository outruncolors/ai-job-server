from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def run_image_prompt_step(
    step_dir: Path,
    step: Any,
    alt: Any,
    rendered_name: str,
    rendered_prompt: str,
    text_output: str,
) -> str:
    """Save an image prompt entry. Returns the output filename.

    Uses the rendered alternative `prompt` as the prompt body; falls back to
    `text_output` when the alternative's prompt is empty.
    """
    from ...image_prompts import create_prompt

    name = (rendered_name or "").strip()
    if not name:
        raise RuntimeError("image_prompt step requires image_prompt_name (after template rendering)")
    body = rendered_prompt.strip() or text_output.strip()
    if not body:
        raise RuntimeError("image_prompt step has no prompt content (rendered prompt and text_output both empty)")

    workflow: Optional[str] = alt.image_prompt_workflow or None
    result = create_prompt(name, body, workflow)
    (step_dir / "output.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return "output.json"
