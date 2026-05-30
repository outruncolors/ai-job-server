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

An entry may carry an optional ``guard`` — a second "editor" prompt that runs
*after* the main prompt's LLM output and either passes it through unchanged (if
it already meets the guard's requirements) or rewrites it to comply. The guard
is itself a compose node (``{prompt, variables}``), so it resolves exactly like
the main prompt; it references the original output via the chain token
``{{previous}}`` (the executor fills it from the prior step's output when the
guard runs as a second LLM step).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class GuardSpec(BaseModel):
    """An optional editor pass attached to a prompt. Shape mirrors a compose
    ``PromptNode`` so it composes the same way as the main prompt; ``enabled``
    lets the guard be authored but switched off without losing the text."""

    enabled: bool = True
    prompt: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


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
    guard: Optional[GuardSpec] = None


class PromptEntryPatch(BaseModel):
    """Editable fields for ``PUT /entries/{id}``. ``app`` and ``key`` are
    deliberately absent — they are stable code contracts, not user-editable.
    """

    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    prompt: Optional[str] = None
    variables: Optional[dict[str, Any]] = None
    guard: Optional[GuardSpec] = None
