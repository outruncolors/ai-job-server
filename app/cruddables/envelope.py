"""The canonical Cruddable envelope + id helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

# Current envelope-format version. Bump if the *shared* meta shape changes (not the
# per-type ``data`` payloads, which version themselves inside ``data`` if needed).
ENVELOPE_SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SLUG_RE = re.compile(r"[^a-z0-9]+")
_DASH_RE = re.compile(r"_+")


def slugify(text: str) -> str:
    """Human-readable, underscore-separated id fragment.

    Lowercases, replaces any run of non-alphanumerics with a single ``_``, and trims
    leading/trailing underscores. Empty input yields ``"item"`` so an id is always
    produced.
    """
    s = _SLUG_RE.sub("_", (text or "").lower())
    s = _DASH_RE.sub("_", s).strip("_")
    return s or "item"


def unique_id(base: str, taken: set[str]) -> str:
    """Return ``base`` if free, else ``base_2``, ``base_3`` … not already in ``taken``."""
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


class Cruddable(BaseModel):
    """One CRUD entity in the unified format. Stored on disk and exported verbatim."""

    schema_version: int = ENVELOPE_SCHEMA_VERSION
    type: str
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    data: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = now_iso()
