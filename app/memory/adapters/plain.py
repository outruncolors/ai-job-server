"""Plain keyword-scoring adapter — the zero-dependency default.

Not meant to be smart. Meant to be deterministic and to make memory usable (and testable)
when memsearch/Milvus is not configured. Scores Markdown records the store lists for the
requested scopes, using substring + token-overlap with title/tag boosts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .. import config, store
from ..models import MemoryHealth, MemoryIndexResult, MemoryRecord, MemoryScope, MemorySearchResult
from .base import MemoryAdapter

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def _snippet(body: str, limit: int = 200) -> str:
    flat = " ".join((body or "").split())
    return flat[:limit]


def _score(record: MemoryRecord, query: str, q_tokens: set[str]) -> float:
    """Bounded 0..1 relevance score. Higher = better; deterministic for a given record."""
    if not q_tokens:
        return 0.0
    title_t = _tokens(record.title)
    body_t = _tokens(record.body)
    tag_t = _tokens(" ".join(record.tags))

    hay = f"{record.title}\n{record.body}".lower()
    substring = 1 if query.strip().lower() and query.strip().lower() in hay else 0
    overlap_title = len(q_tokens & title_t)
    overlap_body = len(q_tokens & body_t)
    overlap_tag = len(q_tokens & tag_t)

    raw = 3.0 * substring + 2.0 * overlap_title + 1.0 * overlap_body + 1.5 * overlap_tag
    if raw <= 0:
        return 0.0
    return round(raw / (raw + 4.0), 4)


class PlainAdapter(MemoryAdapter):
    name = "plain"

    async def health(self) -> MemoryHealth:
        cfg = config.get_config()
        return MemoryHealth(
            enabled=cfg.enabled,
            backend=self.name,
            store_path=cfg.base_dir,
            index_available=True,
            message="Plain keyword backend is ready (no external services required).",
        )

    async def index(self, paths: list[Path], force: bool = False) -> MemoryIndexResult:
        # Plain search reads live files on every query — nothing to index.
        return MemoryIndexResult(
            backend=self.name,
            indexed_files=0,
            skipped_files=len(paths),
            message="plain backend reads live files; no index to build",
        )

    async def search(
        self,
        query: str,
        scopes: list[MemoryScope],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[MemorySearchResult]:
        q_tokens = _tokens(query)
        scored: list[tuple[float, str, MemorySearchResult]] = []
        for record, path in store.list_records(scopes or None, include_deleted=False):
            s = _score(record, query, q_tokens)
            if s <= 0:
                continue
            result = MemorySearchResult(
                memory_id=record.id,
                title=record.title,
                score=s,
                path=str(path),
                snippet=_snippet(record.body),
                metadata={
                    "scope_type": record.scope_type,
                    "scope_id": record.scope_id,
                    "tags": record.tags,
                },
            )
            scored.append((s, record.id, result))
        # deterministic: score desc, then memory_id asc
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [r for _, _, r in scored[:top_k]]

    async def delete(self, memory_id: str) -> None:
        # No index to update; soft-deleted records are skipped at list time.
        return None
