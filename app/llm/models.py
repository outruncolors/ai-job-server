from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ALLOWED_CAPS = {"text", "vision"}


class LLMPreset(BaseModel):
    """A named load configuration for the local llama.cpp manager.

    Resolved at swap time: `model_path` + `args` are passed to `LlamaCppManager`
    to spawn `llama-server` with consistent CLI flags. The preset's full hash
    (model_path + args) is the swap key.
    """

    name: str = Field(..., min_length=1, max_length=80)
    model_path: str = Field(..., min_length=1)
    args: dict = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=lambda: ["text"])
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _KEBAB_RE.match(v):
            raise ValueError(
                "name must be kebab-case (lowercase letters/digits, hyphens between)"
            )
        return v

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("capabilities must include at least 'text'")
        bad = [c for c in v if c not in _ALLOWED_CAPS]
        if bad:
            raise ValueError(
                f"unknown capabilities: {bad}; allowed: {sorted(_ALLOWED_CAPS)}"
            )
        if "text" not in v:
            raise ValueError("capabilities must include 'text'")
        return v

    def to_manager_dict(self) -> dict:
        """Shape consumed by `LlamaCppManager._args_from_preset` / `ensure_loaded`."""
        return {"model_path": self.model_path, "args": dict(self.args)}
