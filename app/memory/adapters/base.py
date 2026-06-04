"""The narrow adapter interface every search backend implements.

The adapter **never owns the canonical write path** — ``store`` writes Markdown files;
the adapter only indexes/searches them and (optionally) drops them from its index. Methods
are async so backends with async clients (memsearch) fit naturally; the plain adapter
implements them with no awaits.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..models import MemoryHealth, MemoryIndexResult, MemoryScope, MemorySearchResult


class MemoryBackendUnavailable(RuntimeError):
    """Raised by an adapter that is configured but cannot serve requests."""


class MemoryAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def health(self) -> MemoryHealth: ...

    @abstractmethod
    async def index(
        self, paths: list[Path], force: bool = False
    ) -> MemoryIndexResult: ...

    @abstractmethod
    async def search(
        self,
        query: str,
        scopes: list[MemoryScope],
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> list[MemorySearchResult]: ...

    @abstractmethod
    async def delete(self, memory_id: str) -> None: ...
