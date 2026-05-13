from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .models import ToolCallError, ToolCallResult
from .registry import get_tool
from .validator import validate_call


def _run_random_integer(args: dict) -> dict:
    lo, hi = args["min"], args["max"]
    if lo > hi:
        raise ValueError(f"min ({lo}) must be <= max ({hi})")
    return {"value": random.randint(lo, hi)}


_EXECUTORS: dict[str, Callable[[dict], Any]] = {
    "random_integer": _run_random_integer,
}


async def execute(name: str, arguments: dict) -> ToolCallResult | ToolCallError:
    ok, err = validate_call(name, arguments)
    if not ok:
        status = "unknown_tool" if get_tool(name) is None else "invalid"
        return ToolCallError(tool=name, error=err or "validation failed", validation_status=status)

    executor = _EXECUTORS.get(name)
    if executor is None:
        return ToolCallError(
            tool=name,
            error=f"No executor registered for tool: {name}",
            validation_status="invalid",
        )

    t0 = time.monotonic()
    try:
        result = executor(arguments)
    except Exception as exc:
        return ToolCallError(
            tool=name,
            error=str(exc),
            validation_status="invalid",
        )

    return ToolCallResult(
        tool=name,
        result=result,
        execution_ms=round((time.monotonic() - t0) * 1000, 2),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
