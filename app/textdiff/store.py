"""Generic proposal persistence keyed by ``(app, scope_key)``.

Stored under ``config/textdiff/<app>/<scope_key>/<proposal_id>.json`` (gitignored,
atomic ``tmp + os.replace``). Apps persist proposals here so a rejected edit's full
before/after stays inspectable (Tomeberry's debug panel reads it back), and so the
``/v1/textdiff`` route can surface any proposal without app knowledge.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from .diff import Proposal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEXTDIFF_DIR: Path = PROJECT_ROOT / "config" / "textdiff"

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe(name: str) -> str:
    return _SAFE_RE.sub("_", name or "").strip("_") or "_"


def _scope_dir(app: str, scope_key: str) -> Path:
    return TEXTDIFF_DIR / _safe(app) / _safe(scope_key)


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_proposal(app: str, scope_key: str, proposal: Proposal) -> Proposal:
    path = _scope_dir(app, scope_key) / f"{proposal.id}.json"
    _atomic_write(path, proposal.model_dump())
    return proposal


def get_proposal(app: str, scope_key: str, proposal_id: str) -> Optional[Proposal]:
    path = _scope_dir(app, scope_key) / f"{_safe(proposal_id)}.json"
    if not path.exists():
        return None
    try:
        return Proposal(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def list_proposals(app: str, scope_key: str) -> list[Proposal]:
    d = _scope_dir(app, scope_key)
    if not d.is_dir():
        return []
    out: list[Proposal] = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(Proposal(**json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def delete_proposal(app: str, scope_key: str, proposal_id: str) -> bool:
    path = _scope_dir(app, scope_key) / f"{_safe(proposal_id)}.json"
    if path.exists():
        path.unlink()
        return True
    return False
