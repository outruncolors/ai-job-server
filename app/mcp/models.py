from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_serializer


class ToolParameter(BaseModel):
    type: str
    description: str
    minimum: int | None = None
    maximum: int | None = None
    default: Any = None

    @model_serializer
    def _ser(self) -> dict:
        out: dict = {"type": self.type, "description": self.description}
        if self.minimum is not None:
            out["minimum"] = self.minimum
        if self.maximum is not None:
            out["maximum"] = self.maximum
        if self.default is not None:
            out["default"] = self.default
        return out


class ToolInputSchema(BaseModel):
    type: str = "object"
    properties: dict[str, ToolParameter]
    required: list[str]
    additionalProperties: bool = False


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: ToolInputSchema


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any]


class ToolCallResult(BaseModel):
    tool: str
    result: Any
    execution_ms: float
    timestamp: str


class ToolCallError(BaseModel):
    tool: str
    error: str
    validation_status: Literal["invalid", "unknown_tool"]
