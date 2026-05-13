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

REGISTRY: dict[str, ToolDefinition] = {
    "random_integer": _random_integer,
    "generate_name": _generate_name,
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
