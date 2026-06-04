"""Service layer — the single app/chain-facing entry point.

Coordinates validation, id generation, path resolution, Markdown read/write, soft
deletion, search orchestration, reindexing, and the dev-only demo fixtures. Apps never
talk to an adapter or to memsearch directly; they call ``get_service()``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.cruddables.envelope import now_iso

from . import config, store
from .adapters.base import MemoryAdapter, MemoryBackendUnavailable
from .adapters.plain import PlainAdapter
from .models import (
    MemoryHealth,
    MemoryIndexResult,
    MemoryRecord,
    MemoryReindexRequest,
    MemoryScope,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryUpdateRequest,
    MemoryWriteRequest,
)

log = logging.getLogger(__name__)

# The only scope the demo fixtures / reset may ever touch. Real app memory is never
# wiped by a test reset.
DEMO_SCOPE = MemoryScope(scope_type="test", scope_id="memory_demo")

_DEMO_MEMORIES = [
    ("mem_demo_alice", "Alice likes red apples", "Alice likes red apples.", ["fruit", "people"]),
    ("mem_demo_bob", "Bob likes blue bicycles", "Bob likes blue bicycles.", ["bikes", "people"]),
    (
        "mem_demo_lighthouse",
        "The lighthouse is north of the harbor",
        "The lighthouse is north of the harbor.",
        ["places"],
    ),
    (
        "mem_demo_atomic",
        "The user prefers atomic UI tests",
        "The user prefers atomic, unit-test-like UI panels for new backend utilities.",
        ["testing", "architecture"],
    ),
]

_DEMO_SEARCHES = [
    ("apples", "Alice likes red apples"),
    ("bicycles", "Bob likes blue bicycles"),
    ("where is the lighthouse", "The lighthouse is north of the harbor"),
    ("testing utilities", "The user prefers atomic UI tests"),
]


class MemoryService:
    def __init__(self, cfg=None):
        self.cfg = cfg or config.get_config()
        self._plain = PlainAdapter()
        self._adapter = self._make_adapter()

    def _make_adapter(self) -> MemoryAdapter:
        if self.cfg.backend == "memsearch":
            try:
                from .adapters.memsearch import MemsearchAdapter

                return MemsearchAdapter(self.cfg)
            except Exception as e:  # pragma: no cover - exercised only when configured
                if self.cfg.require_backend:
                    raise
                log.warning("memsearch unavailable, falling back to plain: %s", e)
                return self._plain
        return self._plain

    # ── health ────────────────────────────────────────────────────────────
    async def health(self) -> MemoryHealth:
        if not self.cfg.enabled:
            return MemoryHealth(
                enabled=False,
                backend=self.cfg.backend,
                store_path=self.cfg.base_dir,
                index_available=False,
                message="Memory subsystem is disabled (MEMORY_ENABLED=false).",
            )
        try:
            return await self._adapter.health()
        except Exception as e:  # pragma: no cover - defensive
            return MemoryHealth(
                enabled=True,
                backend=self.cfg.backend,
                store_path=self.cfg.base_dir,
                index_available=False,
                message=f"Backend health check failed: {e}",
            )

    # ── write / read / update / delete ──────────────────────────────────────
    async def write(self, req: MemoryWriteRequest) -> tuple[MemoryRecord, Path]:
        now = now_iso()
        record = MemoryRecord(
            id=store.new_memory_id(),
            title=req.title,
            scope_type=req.scope.scope_type,
            scope_id=req.scope.scope_id,
            app_id=req.scope.app_id,
            user_id=req.scope.user_id,
            session_id=req.scope.session_id,
            tags=list(req.tags),
            source_type=req.source_type,
            source_ref=req.source_ref,
            importance=req.importance,
            expires_at=req.expires_at,
            supersedes=req.supersedes,
            visibility=req.visibility,
            created_at=now,
            updated_at=now,
            status="active",
            body=req.body,
        )
        path = store.write_record(record)
        await self._index_best_effort([path])
        return record, path

    def read(self, memory_id: str) -> Optional[MemoryRecord]:
        found = store.read_record(memory_id)
        return found[0] if found else None

    async def update(
        self, memory_id: str, req: MemoryUpdateRequest
    ) -> Optional[MemoryRecord]:
        found = store.read_record(memory_id)
        if not found:
            return None
        record, _ = found
        data = req.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(record, field, value)
        record.updated_at = now_iso()
        path = store.write_record(record)
        await self._index_best_effort([path])
        return record

    async def delete(self, memory_id: str) -> Optional[MemoryRecord]:
        """Soft delete: mark status=deleted (file stays on disk) + drop from index."""
        found = store.read_record(memory_id)
        if not found:
            return None
        record, _ = found
        record.status = "deleted"
        record.updated_at = now_iso()
        store.write_record(record)
        try:
            await self._adapter.delete(memory_id)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("adapter.delete failed for %s: %s", memory_id, e)
        return record

    # ── search ──────────────────────────────────────────────────────────────
    async def search(self, req: MemorySearchRequest) -> MemorySearchResponse:
        top_k = req.top_k or self.cfg.top_k_default
        if not self.cfg.enabled:
            return MemorySearchResponse(
                ok=True,
                enabled=False,
                backend=self.cfg.backend,
                query=req.query,
                scopes=req.scopes,
                top_k=top_k,
                count=0,
                results=[],
                message="Memory subsystem is disabled.",
            )
        backend = self._adapter.name
        message = None
        try:
            results = await self._adapter.search(req.query, req.scopes, top_k)
        except MemoryBackendUnavailable as e:
            if self.cfg.require_backend:
                raise
            backend = f"{self._adapter.name}->plain"
            message = f"Primary backend unavailable, used plain fallback: {e}"
            results = await self._plain.search(req.query, req.scopes, top_k)
        return MemorySearchResponse(
            ok=True,
            enabled=True,
            backend=backend,
            query=req.query,
            scopes=req.scopes,
            top_k=top_k,
            count=len(results),
            results=results,
            message=message,
        )

    async def reindex(self, req: MemoryReindexRequest) -> MemoryIndexResult:
        paths = [p for _, p in store.list_records(req.scopes or None, include_deleted=False)]
        return await self._adapter.index(paths, force=req.force)

    async def _index_best_effort(self, paths: list[Path]) -> None:
        try:
            await self._adapter.index(paths)
        except Exception as e:  # pragma: no cover - file is source of truth
            log.warning("adapter.index failed (file written regardless): %s", e)

    # ── prompt formatting helper ────────────────────────────────────────────
    @staticmethod
    def format_memory_block(
        results: list[MemorySearchResult], max_chars: int = 1200
    ) -> str:
        """Turn search results into a compact, deterministic, char-capped prompt block."""
        if not results:
            return ""
        lines = ["Relevant memories:", ""]
        for i, r in enumerate(results, start=1):
            scope = f"{r.metadata.get('scope_type', '?')}/{r.metadata.get('scope_id', '?')}"
            body = r.snippet or r.title
            lines.append(f"{i}. {r.title}")
            lines.append(f"Scope: {scope}")
            lines.append(f"Memory: {body}")
            lines.append("")
        block = "\n".join(lines).rstrip() + "\n"
        if len(block) > max_chars:
            block = block[: max_chars - 1].rstrip() + "…"
        return block

    # ── dev-only demo fixtures (test/memory_demo scope only) ────────────────
    async def create_demo_memories(self) -> list[MemoryRecord]:
        now = now_iso()
        out: list[MemoryRecord] = []
        for mem_id, title, body, tags in _DEMO_MEMORIES:
            record = MemoryRecord(
                id=mem_id,
                title=title,
                scope_type=DEMO_SCOPE.scope_type,
                scope_id=DEMO_SCOPE.scope_id,
                tags=tags,
                source_type="demo",
                created_at=now,
                updated_at=now,
                status="active",
                body=body,
            )
            path = store.write_record(record)
            await self._index_best_effort([path])
            out.append(record)
        return out

    async def run_demo_searches(self) -> list[dict]:
        results = []
        for query, expected in _DEMO_SEARCHES:
            resp = await self.search(
                MemorySearchRequest(query=query, scopes=[DEMO_SCOPE], top_k=3)
            )
            actual = resp.results[0].title if resp.results else None
            results.append(
                {
                    "query": query,
                    "expected_top": expected,
                    "actual_top": actual,
                    "ok": actual == expected,
                    "results": [r.model_dump() for r in resp.results],
                }
            )
        return results

    def reset_demo(self) -> int:
        """Hard-delete every file in the demo scope. Never touches other scopes."""
        return store.delete_files_in_scope(DEMO_SCOPE)


_service: Optional[MemoryService] = None


def get_service() -> MemoryService:
    global _service
    if _service is None:
        _service = MemoryService(config.get_config())
    return _service


def reset_service() -> None:
    """Drop the cached service (tests, or after config changes)."""
    global _service
    _service = None
