from __future__ import annotations

import os
from pathlib import Path

CONTEXT_BASE: Path = Path(os.environ.get(
    "AI_CONTEXT_BASE",
    str(Path(__file__).parent.parent.parent / "context"),
))


def resolve_context_files(paths: list[str]) -> str:
    if not paths:
        return ""
    base = CONTEXT_BASE.resolve()
    parts: list[str] = []
    for rel_path in paths:
        if Path(rel_path).is_absolute():
            raise ValueError(f"Context file path must be relative: {rel_path!r}")
        candidate = (CONTEXT_BASE / rel_path).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Context file path traverses outside context root: {rel_path!r}"
            )
        if not candidate.exists():
            raise FileNotFoundError(f"Context file not found: {rel_path!r}")
        parts.append(candidate.read_text(encoding="utf-8"))
    return "\n\n".join(parts)
