"""Pack file storage over two trees (builtin repo + user config).

Layout: ``<dir>/<type>/<pack_id>.json``. A user pack shadows a builtin pack with
the same ``(type, id)``. Malformed pack files are skipped and logged rather than
aborting a listing.

Both directory roots are module-level constants so tests can monkeypatch them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# app/packs/store.py -> parents[2] == repo root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

BUILTIN_PACKS_DIR = _PROJECT_ROOT / "packs"
USER_PACKS_DIR = _PROJECT_ROOT / "config" / "packs"


def _load_pack_file(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("skipping malformed pack file %s: %s", path, exc)
        return None
    if not isinstance(doc, dict) or "id" not in doc:
        logger.warning("skipping pack file with no id: %s", path)
        return None
    return doc


def _summary(doc: dict, type_name: str, source: str) -> dict:
    items = doc.get("items") or []
    return {
        "id": doc.get("id"),
        "name": doc.get("name") or doc.get("id"),
        "description": doc.get("description", ""),
        "tags": doc.get("tags") or [],
        "type": type_name,
        "item_count": len(items) if isinstance(items, list) else 0,
        "source": source,
    }


def _iter_pack_files(root: Path):
    """Yield (type_name, pack_id, path) for every ``<type>/<id>.json`` under root."""
    if not root.exists():
        return
    for type_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for pack_path in sorted(type_dir.glob("*.json")):
            yield type_dir.name, pack_path.stem, pack_path


def list_packs() -> list[dict]:
    """Return pack summaries from both trees; user packs shadow builtin by (type,id)."""
    by_key: dict[tuple[str, str], dict] = {}
    for source, root in (("builtin", BUILTIN_PACKS_DIR), ("user", USER_PACKS_DIR)):
        for type_name, pack_id, path in _iter_pack_files(root):
            doc = _load_pack_file(path)
            if doc is None:
                continue
            by_key[(type_name, doc.get("id") or pack_id)] = _summary(
                doc, type_name, source
            )
    return sorted(by_key.values(), key=lambda s: (s["type"], (s["name"] or "").lower()))


def get_pack(type_name: str, pack_id: str) -> Optional[dict]:
    """Return the full pack doc for ``(type, id)``; user tree wins over builtin."""
    for root in (USER_PACKS_DIR, BUILTIN_PACKS_DIR):
        path = root / type_name / f"{pack_id}.json"
        if path.exists():
            doc = _load_pack_file(path)
            if doc is not None:
                return doc
    return None
