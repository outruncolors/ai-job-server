from __future__ import annotations

from .registry import get_tool


def validate_call(name: str, arguments: dict) -> tuple[bool, str | None]:
    """Validate a tool call against the registry. Returns (ok, error_message)."""
    tool = get_tool(name)
    if tool is None:
        return False, f"Unknown tool: {name}"

    schema = tool.input_schema

    extra = set(arguments.keys()) - set(schema.properties.keys())
    if extra:
        return False, f"Unexpected arguments: {', '.join(sorted(extra))}"

    for field in schema.required:
        if field not in arguments:
            return False, f"Missing required argument: {field}"

    for field, value in arguments.items():
        param = schema.properties[field]
        if param.type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"Argument '{field}' must be an integer, got {type(value).__name__}"
            if param.minimum is not None and value < param.minimum:
                return False, f"Argument '{field}' must be >= {param.minimum}"
            if param.maximum is not None and value > param.maximum:
                return False, f"Argument '{field}' must be <= {param.maximum}"
        elif param.type == "string":
            if not isinstance(value, str):
                return False, f"Argument '{field}' must be a string"
        elif param.type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"Argument '{field}' must be a number"

    return True, None
