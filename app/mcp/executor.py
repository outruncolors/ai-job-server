from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .data.names import FEMALE_NAMES, LAST_NAMES, MALE_NAMES
from .models import ToolCallError, ToolCallResult
from .registry import get_tool
from .validator import validate_call


def _run_random_integer(args: dict) -> dict:
    lo, hi = args["min"], args["max"]
    if lo > hi:
        raise ValueError(f"min ({lo}) must be <= max ({hi})")
    return {"value": random.randint(lo, hi)}


def _run_generate_name(args: dict) -> dict:
    pool = MALE_NAMES if args["gender"] == "male" else FEMALE_NAMES
    parts = [random.choice(pool)]
    if args.get("include_middle_name", False):
        parts.append(random.choice(pool))
    if args.get("include_last_name", False):
        parts.append(random.choice(LAST_NAMES))
    return {"name": " ".join(parts)}


def _run_format_voice_segments(args: dict) -> dict:
    return args  # arguments are the result; schema validation is the value


def _run_save_image_prompt(args: dict) -> dict:
    from ..image_prompts import create_prompt

    entry = create_prompt(args["name"], args["prompt"], args.get("workflow"))
    return {"id": entry["id"], "name": entry["name"]}


def _run_save_wildcard(args: dict) -> dict:
    from ..wildcards import create_wildcard, list_wildcards, update_wildcard

    name = args["name"]
    value = args["value"]
    mode = args.get("mode", "append")
    new_entry = {"text": value}
    if mode == "create":
        wc = create_wildcard(name, [new_entry], "")
        return {"id": wc["id"], "name": wc["name"], "action": "create"}
    existing = next((w for w in list_wildcards() if w.get("name") == name), None)
    if existing is None:
        wc = create_wildcard(name, [new_entry], "")
        return {"id": wc["id"], "name": wc["name"], "action": "create_missing"}
    merged_entries = list(existing.get("entries") or []) + [new_entry]
    wc = update_wildcard(
        existing["id"], existing["name"], merged_entries, existing.get("description") or ""
    )
    return {"id": wc["id"], "name": wc["name"], "action": "append"}


def _run_create_ticket(args: dict) -> dict:
    from ..tickets.store import create_ticket

    ticket = create_ticket(
        args["title"], args.get("description", ""), list(args.get("file_hints") or [])
    )
    return {"id": ticket["id"], "title": ticket["title"]}


_EXECUTORS: dict[str, Callable[[dict], Any]] = {
    "random_integer": _run_random_integer,
    "generate_name": _run_generate_name,
    "format_voice_segments": _run_format_voice_segments,
    "save_image_prompt": _run_save_image_prompt,
    "save_wildcard": _run_save_wildcard,
    "create_ticket": _run_create_ticket,
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
