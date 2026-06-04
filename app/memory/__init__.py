"""App-agnostic memory subsystem.

Markdown files under ``config/memory`` are the durable source of truth; the search
backend (plain keyword scorer by default, optional memsearch/Milvus) is a swappable
implementation detail behind ``adapters.base.MemoryAdapter``.

See ``docs/memory/index.md`` for the full contract.
"""

from __future__ import annotations

from .models import (
    MemoryHealth,
    MemoryIndexResult,
    MemoryRecord,
    MemoryScope,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
    MemoryWriteRequest,
)
from .service import get_service, reset_service

__all__ = [
    "MemoryHealth",
    "MemoryIndexResult",
    "MemoryRecord",
    "MemoryScope",
    "MemorySearchRequest",
    "MemorySearchResponse",
    "MemorySearchResult",
    "MemoryWriteRequest",
    "get_service",
    "reset_service",
]
