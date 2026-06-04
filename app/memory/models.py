"""Pydantic v2 models for the memory subsystem.

A ``MemoryRecord`` is the in-memory form of one Markdown file: its frontmatter is the
metadata, its ``body`` is the Markdown body (preserved byte-exact on disk).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ScopeType = Literal[
    "global",
    "app",
    "project",
    "user",
    "session",
    "character",
    "custom",
    "test",
]

# Required + optional frontmatter keys, per the design primer. Anything else found in a
# file's frontmatter is preserved under ``MemoryRecord.extra``.
_RECORD_META_FIELDS = (
    "id",
    "title",
    "scope_type",
    "scope_id",
    "app_id",
    "user_id",
    "session_id",
    "tags",
    "source_type",
    "source_ref",
    "importance",
    "created_at",
    "updated_at",
    "status",
    "expires_at",
    "supersedes",
    "visibility",
)


class MemoryScope(BaseModel):
    """Ownership/context of a memory. Some callers only set ``app_id``; others combine
    ``app_id + character_id + session_id`` via the typed fields below."""

    scope_type: ScopeType
    scope_id: str = "global"
    app_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None

    def key(self) -> str:
        return f"{self.scope_type}/{self.scope_id}"


class MemoryRecord(BaseModel):
    """One memory. Required meta: id/title/scope_type/scope_id/created_at/updated_at/status."""

    id: str
    title: str
    scope_type: ScopeType
    scope_id: str = "global"
    created_at: str
    updated_at: str
    status: Literal["active", "deleted"] = "active"
    # optional metadata
    app_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    importance: Optional[float] = None
    expires_at: Optional[str] = None
    supersedes: Optional[str] = None
    visibility: Optional[str] = None
    # any unrecognised frontmatter keys, round-tripped verbatim
    extra: dict[str, Any] = Field(default_factory=dict)
    # the Markdown body (not part of the frontmatter)
    body: str = ""

    def scope(self) -> MemoryScope:
        return MemoryScope(
            scope_type=self.scope_type,
            scope_id=self.scope_id,
            app_id=self.app_id,
            user_id=self.user_id,
            session_id=self.session_id,
        )

    def frontmatter(self) -> dict[str, Any]:
        """The metadata dict to serialize as YAML frontmatter (excludes ``body``)."""
        meta: dict[str, Any] = {}
        for f in _RECORD_META_FIELDS:
            meta[f] = getattr(self, f)
        # carry through any unknown keys read from disk
        for k, v in self.extra.items():
            if k not in meta:
                meta[k] = v
        return meta


# ── request / response models ────────────────────────────────────────────────


class MemoryWriteRequest(BaseModel):
    title: str
    body: str = ""
    scope: MemoryScope
    tags: list[str] = Field(default_factory=list)
    source_type: Optional[str] = "manual"
    source_ref: Optional[str] = None
    importance: Optional[float] = None
    expires_at: Optional[str] = None
    supersedes: Optional[str] = None
    visibility: Optional[str] = None


class MemoryUpdateRequest(BaseModel):
    """Partial update — only provided fields change."""

    title: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[Literal["active", "deleted"]] = None
    importance: Optional[float] = None
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    visibility: Optional[str] = None


class MemorySearchRequest(BaseModel):
    query: str
    scopes: list[MemoryScope] = Field(default_factory=list)
    top_k: Optional[int] = None


class MemoryReindexRequest(BaseModel):
    scopes: list[MemoryScope] = Field(default_factory=list)
    force: bool = False


class MemorySearchResult(BaseModel):
    memory_id: str
    title: str
    score: float
    path: str
    snippet: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchResponse(BaseModel):
    """Search results plus echoed inputs — everything needed to debug a query."""

    ok: bool = True
    enabled: bool = True
    backend: str
    query: str
    scopes: list[MemoryScope] = Field(default_factory=list)
    top_k: int
    count: int
    results: list[MemorySearchResult] = Field(default_factory=list)
    message: Optional[str] = None


class MemoryHealth(BaseModel):
    enabled: bool
    backend: str
    store_path: str
    index_available: bool
    message: str


class MemoryIndexResult(BaseModel):
    ok: bool = True
    backend: str
    indexed_files: int = 0
    skipped_files: int = 0
    message: Optional[str] = None
