"""Memory subsystem configuration.

Follows the project's config-singleton convention (see ``app/comfyui/config.py``):
a module-level path constant overridable via env, plus a lazily-built, resettable
singleton. Tests ``monkeypatch.setattr`` ``BASE_DIR`` and reset ``_config``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# Where Markdown memory files live. ``config/`` is gitignored, so memory records and the
# optional Milvus-Lite db stay local to the node. Overridable for tests / multi-machine.
BASE_DIR: Path = Path(
    os.environ.get("MEMORY_BASE_DIR", str(PROJECT_ROOT / "config" / "memory"))
)


class MemoryConfig(BaseModel):
    enabled: bool = True
    backend: str = "plain"  # "plain" | "memsearch"
    base_dir: str
    top_k_default: int = 5
    # When True, a configured-but-unavailable memsearch backend is a hard error
    # (search/health surface it) instead of silently falling back to plain.
    require_backend: bool = False
    memsearch_collection: str = "ai_job_server_memory"
    memsearch_uri: str = ""
    memsearch_token: Optional[str] = None

    @property
    def base_path(self) -> Path:
        return Path(self.base_dir)


_config: Optional[MemoryConfig] = None


def load_config() -> MemoryConfig:
    """Build the config from the environment + current ``BASE_DIR`` and cache it."""
    global _config
    default_uri = str(BASE_DIR / ".memsearch" / "milvus.db")
    _config = MemoryConfig(
        enabled=_env_bool("MEMORY_ENABLED", True),
        backend=os.environ.get("MEMORY_BACKEND", "plain").strip() or "plain",
        base_dir=str(BASE_DIR),
        top_k_default=int(os.environ.get("MEMORY_TOP_K_DEFAULT", "5")),
        require_backend=_env_bool("MEMORY_REQUIRE_BACKEND", False),
        memsearch_collection=os.environ.get(
            "MEMORY_MEMSEARCH_COLLECTION", "ai_job_server_memory"
        ),
        memsearch_uri=os.environ.get("MEMORY_MEMSEARCH_URI") or default_uri,
        memsearch_token=os.environ.get("MEMORY_MEMSEARCH_TOKEN") or None,
    )
    return _config


def get_config() -> MemoryConfig:
    global _config
    if _config is None:
        return load_config()
    return _config


def reset_config() -> None:
    """Drop the cached config (used by tests after monkeypatching ``BASE_DIR``)."""
    global _config
    _config = None
