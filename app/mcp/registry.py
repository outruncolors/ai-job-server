from __future__ import annotations

from .models import ToolDefinition, ToolInputSchema, ToolParameter

_random_integer = ToolDefinition(
    name="random_integer",
    description=(
        "Generate a random integer within an inclusive range. "
        "Use this when a task requires an unpredictable integer value."
    ),
    input_schema=ToolInputSchema(
        properties={
            "min": ToolParameter(
                type="integer",
                description="Inclusive minimum value.",
            ),
            "max": ToolParameter(
                type="integer",
                description="Inclusive maximum value.",
            ),
        },
        required=["min", "max"],
    ),
)

_generate_name = ToolDefinition(
    name="generate_name",
    description=(
        "Generate a random US name based on gender. "
        "Optionally include a middle name and/or last name."
    ),
    input_schema=ToolInputSchema(
        properties={
            "gender": ToolParameter(
                type="string",
                description="Gender of the name to generate.",
                enum=["male", "female"],
            ),
            "include_middle_name": ToolParameter(
                type="boolean",
                description="Whether to include a middle name.",
                default=False,
            ),
            "include_last_name": ToolParameter(
                type="boolean",
                description="Whether to include a last name.",
                default=False,
            ),
        },
        required=["gender"],
    ),
)

_format_voice_segments = ToolDefinition(
    name="format_voice_segments",
    description=(
        "Format analyzed text as voice segments with natural pause timings. "
        "Call this once with all segments when you have identified the natural "
        "pause boundaries in the text."
    ),
    input_schema=ToolInputSchema(
        properties={
            "segments": ToolParameter(
                type="array",
                description="Ordered list of text segments with pause durations.",
                items={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text for this segment."},
                        "delay_ms": {
                            "type": "integer",
                            "description": "Silence after this segment in ms. Use 0 for the last segment.",
                            "minimum": 0,
                            "maximum": 30000,
                        },
                    },
                    "required": ["text", "delay_ms"],
                },
            ),
        },
        required=["segments"],
    ),
)

REGISTRY: dict[str, ToolDefinition] = {
    "random_integer": _random_integer,
    "generate_name": _generate_name,
    "format_voice_segments": _format_voice_segments,
}


def list_tools() -> list[ToolDefinition]:
    return list(REGISTRY.values())


def get_tool(name: str) -> ToolDefinition | None:
    return REGISTRY.get(name)


def to_openai_schema(tool: ToolDefinition) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema.model_dump(),
        },
    }


def resolve_tools(names: list[str]) -> list[ToolDefinition]:
    import logging
    log = logging.getLogger(__name__)
    result = []
    for name in names:
        td = get_tool(name)
        if td is None:
            log.warning("MCP tool %r not found in registry — skipping", name)
        else:
            result.append(td)
    return result
