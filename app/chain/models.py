from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChainLLMConfig(BaseModel):
    api_base: str
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)


class ChainStep(BaseModel):
    id: Optional[str] = None
    name: str
    type: Literal["llm", "voice", "write_context", "sequence"] = "llm"
    sequence_id: Optional[str] = None
    prompt: str = ""
    context_ids: list[str] = []
    tools: list[str] = []
    voice_preset_id: Optional[str] = None
    voice_pre: Optional[str] = None
    voice_post: Optional[str] = None
    voice_preprocess: bool = False
    ctx_name: Optional[str] = None
    ctx_description: Optional[str] = None
    ctx_pre: Optional[str] = None
    ctx_post: Optional[str] = None
    ctx_tags: list[str] = []
    ctx_overwrite: bool = False


class ChainJobRequest(BaseModel):
    title: Optional[str] = None
    input: str = Field(default="")
    llm: ChainLLMConfig
    steps: list[ChainStep] = Field(min_length=1)


class ChainStepStatus(BaseModel):
    id: str
    name: str
    type: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    output_file: Optional[str] = None
