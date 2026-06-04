"""Optional memsearch (Zilliz) adapter — semantic search over the same Markdown files.

Defensive by design: ``memsearch`` is imported lazily so the server boots (on the plain
backend) even when it is not installed. Markdown files remain the source of truth — this
adapter only indexes/searches them via Milvus-Lite. Soft-deleted records are filtered out
when mapping chunk hits back to memory records, so no per-id index deletion is needed.

memsearch result dicts expose ``content``/``source``/``heading``/``score``; all accessors
are guarded since that schema is not version-pinned. ``source_prefix`` (a resolved path
prefix) gives us scope filtering for free.

Embedding defaults to the local ONNX bge-m3 model (no API key); the model downloads from
HuggingFace on first index/search. Override via ``MEMORY_MEMSEARCH_EMBED_PROVIDER``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from .. import store
from ..models import MemoryHealth, MemoryIndexResult, MemoryScope, MemorySearchResult
from .base import MemoryAdapter, MemoryBackendUnavailable


def _import_memsearch():
    try:
        from memsearch import MemSearch  # type: ignore

        return MemSearch
    except Exception as e:  # ImportError or transitive failure
        raise MemoryBackendUnavailable(f"memsearch not importable: {e}") from e


class MemsearchAdapter(MemoryAdapter):
    name = "memsearch"

    def __init__(self, cfg):
        self.cfg = cfg
        # Verify importability eagerly so the service can fall back to plain at startup
        # (per its require_backend policy) rather than failing the first request.
        self._MemSearch = _import_memsearch()
        self._client = None
        self._embed_provider = os.environ.get(
            "MEMORY_MEMSEARCH_EMBED_PROVIDER", "onnx"
        )

    def _base(self) -> Path:
        return Path(self.cfg.base_dir)

    def _get_client(self):
        if self._client is None:
            uri = self.cfg.memsearch_uri
            Path(uri).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self._base().mkdir(parents=True, exist_ok=True)
            self._client = self._MemSearch(
                paths=[str(self._base())],
                embedding_provider=self._embed_provider,
                milvus_uri=uri,
                milvus_token=self.cfg.memsearch_token,
                collection=self.cfg.memsearch_collection,
            )
        return self._client

    async def health(self) -> MemoryHealth:
        # Importability + config only — does NOT trigger the embedding-model download.
        try:
            self._get_client()
            available = True
            message = (
                f"memsearch ready (provider={self._embed_provider}, "
                f"collection={self.cfg.memsearch_collection})."
            )
        except Exception as e:
            available = False
            message = f"memsearch unavailable: {e}"
        return MemoryHealth(
            enabled=self.cfg.enabled,
            backend=self.name,
            store_path=self.cfg.base_dir,
            index_available=available,
            message=message,
        )

    async def index(self, paths: list[Path], force: bool = False) -> MemoryIndexResult:
        try:
            client = self._get_client()
            count = await client.index(force=force)
        except MemoryBackendUnavailable:
            raise
        except Exception as e:
            raise MemoryBackendUnavailable(f"index failed: {e}") from e
        return MemoryIndexResult(
            backend=self.name,
            indexed_files=int(count or 0),
            skipped_files=0,
            message="indexed via memsearch (Milvus-Lite)",
        )

    async def search(
        self,
        query: str,
        scopes: list[MemoryScope],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[MemorySearchResult]:
        try:
            client = self._get_client()
        except Exception as e:
            raise MemoryBackendUnavailable(f"client init failed: {e}") from e

        prefixes: list[Optional[str]]
        if scopes:
            prefixes = [str(store.scope_dir(s)) for s in scopes]
        else:
            prefixes = [None]

        raw_hits: list[dict] = []
        try:
            for prefix in prefixes:
                hits = await client.search(query, top_k=top_k, source_prefix=prefix)
                raw_hits.extend(hits or [])
        except Exception as e:
            raise MemoryBackendUnavailable(f"search failed: {e}") from e

        return self._map_hits(raw_hits, top_k)

    def _map_hits(self, raw_hits: list[dict], top_k: int) -> list[MemorySearchResult]:
        # best hit per source file; skip soft-deleted / unreadable records
        best: dict[str, tuple[float, MemorySearchResult]] = {}
        for hit in raw_hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("source")
            if not source:
                continue
            try:
                score = float(hit.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            record = self._record_for(source)
            if record is None or record.status != "active":
                continue
            content = hit.get("content") or record.body
            snippet = " ".join(str(content).split())[:200]
            result = MemorySearchResult(
                memory_id=record.id,
                title=record.title,
                score=round(score, 4),
                path=str(source),
                snippet=snippet,
                metadata={
                    "scope_type": record.scope_type,
                    "scope_id": record.scope_id,
                    "tags": record.tags,
                    "heading": hit.get("heading"),
                },
            )
            prev = best.get(record.id)
            if prev is None or score > prev[0]:
                best[record.id] = (score, result)

        ranked = sorted(best.values(), key=lambda t: (-t[0], t[1].memory_id))
        return [r for _, r in ranked[:top_k]]

    @staticmethod
    def _record_for(source: str):
        try:
            text = Path(source).read_text(encoding="utf-8")
            return store.parse(text)
        except Exception:
            return None

    async def delete(self, memory_id: str) -> None:
        # Soft-deleted records are filtered at result-mapping time; the next reindex
        # refreshes chunks. No per-id Milvus deletion required.
        return None
