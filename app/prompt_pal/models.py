"""Pydantic schemas for Prompt Pal entries.

A **prompt entry** is a single persisted prompt with metadata. ``id`` /
``schema_version`` / timestamps are server-assigned. ``app`` + ``key`` form the
logical key code references (e.g. ``("hoodat", "field.appearance.primary_outfit")``);
``id`` is the stable surrogate used for deep-links (``?highlight=<id>``) and the
on-disk filename. ``prompt`` + ``variables`` are exactly a compose ``PromptNode``,
so ``compose({"prompt": entry.prompt, "variables": entry.variables})`` resolves it.

- ``PromptEntry`` — the full, persisted document.
- ``PromptEntryPatch`` — the editable subset (``app`` / ``key`` are immutable
  because they are code contracts).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PromptEntry(BaseModel):
    """A persisted Prompt Pal entry (schema v1)."""

    id: str
    schema_version: Literal[1] = 1
    created_at: str
    updated_at: str

    app: str
    key: str
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    prompt: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


class PromptEntryPatch(BaseModel):
    """Editable fields for ``PUT /entries/{id}``. ``app`` and ``key`` are
    deliberately absent — they are stable code contracts, not user-editable.
    """

    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    prompt: Optional[str] = None
    variables: Optional[dict[str, Any]] = None
