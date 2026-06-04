"""Search adapters. The plain adapter is always available; memsearch is optional."""

from __future__ import annotations

from .base import MemoryAdapter
from .plain import PlainAdapter

__all__ = ["MemoryAdapter", "PlainAdapter"]
