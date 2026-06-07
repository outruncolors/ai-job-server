from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


STEP_TYPES = (
    "llm",
    "voice",
    "write_context",
    "sequence",
    "image_prompt",
    "save_wildcard",
    "create_ticket",
    "goto",
)


# Fields that live on an Alternative. When ChainStep is constructed from a v1-style
# flat dict (no `alternatives` key), all matching keys are moved into a single
# alternative so the persisted shape is always v2.
_ALTERNATIVE_FIELDS = {
    "weight",
    "prompt",
    "context_ids",
    "tools",
    "voice_preset_id",
    "voice_pre",
    "voice_post",
    "voice_preprocess",
    "voice_auto_segment",
    "ctx_name",
    "ctx_description",
    "ctx_pre",
    "ctx_post",
    "ctx_tags",
    "ctx_overwrite",
    "preset",
    "requires",
    "sequence_id",
    "image_prompt_name",
    "image_prompt_workflow",
    "wildcard_name",
    "wildcard_mode",
    "ticket_title_template",
    "ticket_description_template",
    "ticket_file_hints",
    "target_step",
    "fall_through",
    "memory",
    "messages",
    "thinking",
}


# Project-wide default for whether an LLM step uses reasoning. Thinking is the
# default (it improves utility/JSON prompts); only steps that explicitly set
# `thinking=False` (e.g. an in-character roleplay reply) suppress it.
DEFAULT_THINKING = True


class ChainLLMConfig(BaseModel):
    api_base: str
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    # Passed through verbatim as the OpenAI-compatible `chat_template_kwargs`
    # request field (llama.cpp honors it; servers that don't simply ignore it).
    # Used e.g. to disable a reasoning model's thinking: {"enable_thinking": False}.
    chat_template_kwargs: Optional[dict] = None
    # Per-request reasoning budget sent to llama.cpp as `thinking_budget_tokens`
    # (0 = end thinking immediately / off; -1 = unrestricted / on). Honored only
    # when the server was launched WITHOUT a --reasoning-budget flag (CLI default
    # -1). Resolved per LLM step by the executor from `Alternative.thinking`.
    thinking_budget_tokens: Optional[int] = None


class SequenceVariable(BaseModel):
    name: str
    default: str = ""
    choices: list[str] = []


class MemoryStepConfig(BaseModel):
    """Optional per-LLM-step memory retrieval. When enabled, the runner searches the
    memory subsystem before rendering and exposes the formatted block as ``{{<inject_as>}}``
    (``{{memory}}`` by default). ``query`` and each scope's ``scope_id`` are templated."""

    enabled: bool = True
    query: str = "{{input}}"
    scopes: list[dict] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1)
    inject_as: str = "memory"
    max_chars: int = Field(default=1200, ge=1)


class Alternative(BaseModel):
    weight: int = Field(default=1, ge=1)
    # llm / generic prompt
    prompt: str = ""
    context_ids: list[str] = []
    tools: list[str] = []
    # voice
    voice_preset_id: Optional[str] = None
    voice_pre: Optional[str] = None
    voice_post: Optional[str] = None
    voice_preprocess: bool = False
    voice_auto_segment: bool = False
    # write_context
    ctx_name: Optional[str] = None
    ctx_description: Optional[str] = None
    ctx_pre: Optional[str] = None
    ctx_post: Optional[str] = None
    ctx_tags: list[str] = []
    ctx_overwrite: bool = False
    # llm preset routing
    preset: Optional[str] = None
    requires: list[str] = []
    # reasoning control (llm steps): None = project default (DEFAULT_THINKING),
    # True/False force reasoning on/off via the per-request thinking budget.
    thinking: Optional[bool] = None
    # sequence reference
    sequence_id: Optional[str] = None
    # new step types
    image_prompt_name: Optional[str] = None
    image_prompt_workflow: Optional[str] = None
    wildcard_name: Optional[str] = None
    wildcard_mode: Literal["append", "create"] = "append"
    ticket_title_template: Optional[str] = None
    ticket_description_template: Optional[str] = None
    ticket_file_hints: list[str] = []
    # goto
    target_step: Optional[int] = None
    fall_through: bool = False
    # optional memory retrieval (llm steps): populates {{memory}} before rendering
    memory: Optional[MemoryStepConfig] = None
    # optional structured chat (llm steps, no-tools only): a role array whose
    # `content` values are templates rendered with the same token set as `prompt`
    # (+ {{memory}}). When set, the step sends these messages instead of wrapping
    # the single `prompt` in one user turn — so callers can hand the model a real
    # sequenced conversation. Each item: {"role": "system"|"user"|"assistant",
    # "content": "<template>"}. Ignored when `tools` is set.
    messages: Optional[list[dict]] = None


class ChainStep(BaseModel):
    number: int = 0
    id: Optional[str] = None
    name: str
    type: Literal[
        "llm",
        "voice",
        "write_context",
        "sequence",
        "image_prompt",
        "save_wildcard",
        "create_ticket",
        "goto",
    ] = "llm"
    visit_cap: int = Field(default=100, ge=1)
    alternatives: list[Alternative] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _hoist_v1_shorthand(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("alternatives"):
            return data
        # Move any alternative-shaped keys into a single-element alternatives list.
        hoisted: dict = {}
        for key in list(data.keys()):
            if key in _ALTERNATIVE_FIELDS:
                hoisted[key] = data.pop(key)
        if hoisted or not data.get("alternatives"):
            data["alternatives"] = [hoisted] if hoisted else [{}]
        return data

    @model_validator(mode="after")
    def _check_min_alternatives(self) -> "ChainStep":
        if not self.alternatives:
            raise ValueError("step must have at least one alternative")
        return self

    @property
    def primary(self) -> Alternative:
        """First alternative — convenient for callers that don't care about branching."""
        return self.alternatives[0]


class ChainJobRequest(BaseModel):
    schema_version: int = 2
    title: Optional[str] = None
    input: str = Field(default="")
    # Optional: when omitted, the route handler fills it via
    # get_default_as_chain_llm_config() — which itself falls back to the `llm`
    # peer (gpu.local) when no endpoint preset is configured. ensure_loaded_for_step
    # then overrides api_base/model at run time anyway, so this is effectively a
    # base config that callers rarely need to specify.
    llm: Optional[ChainLLMConfig] = None
    steps: list[ChainStep] = Field(min_length=1)
    variables: dict[str, str] = {}
    sequence_variables: list[SequenceVariable] = []


class ChainStepStatus(BaseModel):
    id: str
    name: str
    type: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    output_file: Optional[str] = None
