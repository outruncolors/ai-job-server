from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run_create_ticket_step(
    step_dir: Path,
    step: Any,
    alt: Any,
    rendered_title: str,
    rendered_description: str,
    text_output: str,
) -> str:
    """Create a ticket from the chosen alternative. Returns the output filename.

    Title comes from the rendered alternative `ticket_title_template`. Description
    comes from the rendered `ticket_description_template`, falling back to `text_output`.
    """
    from ...tickets.store import create_ticket

    title = (rendered_title or "").strip()
    if not title:
        raise RuntimeError("create_ticket step requires ticket_title_template (after rendering)")
    description = rendered_description.strip() or text_output.strip()
    file_hints = list(alt.ticket_file_hints or [])

    result = create_ticket(title, description, file_hints)
    (step_dir / "output.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return "output.json"
