"""Tomeberry data model — tales, concepts (3 classes), assistant messages, traces.

A **tale** is a tale-scoped project folder. **Concepts** are the unit of meaning and
cover all three classes:

- ``structural_unit`` — beat|scene|section|chapter|part|tale. Container; ``parent_id``
  / ``children`` / ``order`` are authoritative (the manuscript tree).
- ``narrative_construct`` — premise|arc|plotline|theme|… Non-container; relates via
  typed ``links[]``.
- ``story_entity`` — character|place|object|event|… Non-container; relates via ``links[]``.

The request **trace** is intentionally a loose dict (see B2) — it evolves with the
debug panel and shouldn't be over-constrained by a model.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConceptClass(str, Enum):
    structural_unit = "structural_unit"
    narrative_construct = "narrative_construct"
    story_entity = "story_entity"


# Allowed types per class (advisory — stored as plain strings, validated on create).
STRUCTURAL_TYPES = {"beat", "scene", "section", "chapter", "part", "tale"}
NARRATIVE_TYPES = {
    "premise", "arc", "character_arc", "relationship_arc", "plotline",
    "thread", "conflict", "theme", "mystery", "promise",
}
ENTITY_TYPES = {
    "character", "group", "place", "object", "event",
    "system", "condition", "information", "relationship", "resource",
}

MODES = [
    "discover", "organize", "draft", "revise", "edit",
    "diagnose", "develop", "track", "plan", "publish",
]


class Link(BaseModel):
    rel: str
    target_id: str
    note: str = ""


class HistoryEntry(BaseModel):
    at: str
    kind: str  # manual_edit | proposed | accepted | rejected | iterated
    request_id: Optional[str] = None
    mode: Optional[str] = None
    diff_id: Optional[str] = None
    summary: str = ""


class ConceptMetadata(BaseModel):
    model_generated: bool = False
    source_request_id: Optional[str] = None
    word_count: int = 0
    status: str = "draft"  # draft | revised | final
    tags: list[str] = Field(default_factory=list)


class Concept(BaseModel):
    schema_version: int = 1
    id: str
    concept_class: ConceptClass
    type: str
    title: str = ""
    body: str = ""
    links: list[Link] = Field(default_factory=list)
    parent_id: Optional[str] = None
    children: list[str] = Field(default_factory=list)
    order: int = 0
    metadata: ConceptMetadata = Field(default_factory=ConceptMetadata)
    history: list[HistoryEntry] = Field(default_factory=list)
    created_at: str
    updated_at: str


class TaleSettings(BaseModel):
    model_preset: Optional[str] = None
    change_policy_overrides: dict[str, str] = Field(default_factory=dict)
    workspace_dir: str = ""


class Tale(BaseModel):
    schema_version: int = 1
    type: str = "tomeberry_tale"
    id: str
    title: str
    premise_id: Optional[str] = None
    structural_root_id: Optional[str] = None
    default_mode: str = "draft"
    default_saved_prompt: Optional[str] = None
    settings: TaleSettings = Field(default_factory=TaleSettings)
    created_at: str
    updated_at: str


# ---- assistant pane --------------------------------------------------------


class ProposalRef(BaseModel):
    diff_id: str
    scope: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"  # pending | accepted | rejected | superseded
    target_concept_id: Optional[str] = None


class AssistantMessage(BaseModel):
    id: str
    role: str  # user | assistant | marker
    kind: str = "chat"  # chat | mode_switch | saved_prompt | status | proposal
    text: str = ""
    at: str
    mode: Optional[str] = None
    saved_prompt_key: Optional[str] = None
    request_id: Optional[str] = None
    proposal: Optional[ProposalRef] = None
    context_refs: list[str] = Field(default_factory=list)


# ---- request / route bodies ------------------------------------------------


class TaleCreate(BaseModel):
    title: str
    premise: str = ""
    default_mode: str = "draft"


class TaleUpdate(BaseModel):
    title: Optional[str] = None
    default_mode: Optional[str] = None
    default_saved_prompt: Optional[str] = None
    settings: Optional[TaleSettings] = None


class PremiseUpdate(BaseModel):
    body: str


class ConceptCreate(BaseModel):
    concept_class: ConceptClass
    type: str
    title: str = ""
    body: str = ""
    parent_id: Optional[str] = None
    order: Optional[int] = None
    links: list[Link] = Field(default_factory=list)
    metadata: Optional[ConceptMetadata] = None


class ConceptPatch(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    type: Optional[str] = None
    order: Optional[int] = None
    metadata: Optional[ConceptMetadata] = None


class MoveBody(BaseModel):
    parent_id: Optional[str] = None
    order: int = 0


class LinkCreate(BaseModel):
    rel: str
    target_id: str
    note: str = ""


class IterateBody(BaseModel):
    text: str = ""


class ApplyTemplateBody(BaseModel):
    template_id: str


class RequestCreate(BaseModel):
    text: str = ""
    mode: Optional[str] = None
    saved_prompt_key: Optional[str] = None
    active_pane: str = "content"
    current_unit_id: Optional[str] = None
    scope: Optional[dict[str, Any]] = None  # {kind, selected_text, char_range}
    iterate_of: Optional[str] = None
    context_concept_ids: list[str] = Field(default_factory=list)
