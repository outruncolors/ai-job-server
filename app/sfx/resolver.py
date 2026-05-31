"""SFX resolution: roll → chooser → guard → weighted-random variant.

Platform-level and decoupled from any app: callers pass the line's text/type plus
the participant's identity and the conversation's enabled global domains, and get
back a compact descriptor (persisted on a transcript item) and a verbose trace.

The chance roll happens BEFORE any LLM call. When it passes, a single 2-step LLM
chain runs the editable Prompt Pal ``sfx.choose_emote`` prompt followed by its
guard (``{{previous}}`` = the chooser's JSON). The chooser's own output is read
from its step dir; the guard's keep/reject verdict is the chain's final output.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..chain.executor import execute_chain_job
from ..chain.models import Alternative, ChainJobRequest, ChainLLMConfig, ChainStep
from ..jobs import create_job, find_job_dir
from ..llm_config import get_default_as_chain_llm_config
from ..prompt_pal.service import get_guard, get_text
from . import store

ELIGIBLE_TYPES = ("action", "narration")
SFX_SCHEMA_VERSION = 1
_JOB_TYPE = "sfx_resolve"
_PROMPT_KEY = ("sfx", "choose_emote")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _loads_object(raw: str) -> Optional[dict]:
    """Parse a JSON object, tolerating fences and surrounding prose."""
    try:
        data = json.loads(_strip_fences(raw))
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _read_step_output(job_dir: Path, step_id: str) -> str:
    for p in sorted(job_dir.glob(f"steps/*_{step_id}/output.txt")):
        return p.read_text(encoding="utf-8")
    return ""


def _llm_step(number: int, step_id: str, name: str, prompt: str) -> ChainStep:
    return ChainStep(number=number, id=step_id, name=name, type="llm",
                     alternatives=[Alternative(prompt=prompt)])


def _resolve_llm(llm: Optional[ChainLLMConfig]) -> ChainLLMConfig:
    if llm is None:
        llm = get_default_as_chain_llm_config()
    if llm.chat_template_kwargs is None:  # prose/JSON, not a reasoning trace
        llm = llm.model_copy(update={"chat_template_kwargs": {"enable_thinking": False}})
    return llm


def _build_pool(identity: Optional[str], domains: Optional[list[str]]) -> list[store.PoolEntry]:
    pool: list[store.PoolEntry] = []
    if identity:
        pool.extend(store.identity_pool(identity))
    for domain in domains or []:
        pool.extend(store.domain_pool(domain))
    return pool


def _descriptor(status: str, **extra) -> dict:
    return {"schema_version": SFX_SCHEMA_VERSION, "status": status,
            "created_at": _now(), **extra}


async def resolve_sfx(
    *,
    item_type: str,
    item_text: str,
    author: str = "model",
    identity: Optional[str] = None,
    domains: Optional[list[str]] = None,
    character_label: str = "",
    chance: float = 1.0,
    llm: Optional[ChainLLMConfig] = None,
    rng: Optional[random.Random] = None,
    force: bool = False,
) -> tuple[dict, dict]:
    """Resolve one SFX cue. Returns (descriptor, trace).

    descriptor.status ∈ {skipped, none, rejected, resolved, error}. The chance
    roll runs before any LLM call; ``force`` (reroll) skips it.
    """
    chooser = rng or random
    trace: dict = {"eligible": item_type in ELIGIBLE_TYPES, "type": item_type,
                   "identity": identity, "domains": list(domains or [])}

    if item_type not in ELIGIBLE_TYPES:
        desc = _descriptor("skipped", reason="ineligible_type")
        trace["result"] = desc
        return desc, trace

    if not force:
        roll = chooser.random()
        trace["roll"] = roll
        trace["threshold"] = chance
        if roll > chance:
            desc = _descriptor("skipped", reason="chance_roll", roll=roll, threshold=chance)
            trace["result"] = desc
            return desc, trace

    pool = _build_pool(identity, domains)
    if not pool:
        desc = _descriptor("none", reason="empty_catalog")
        trace["result"] = desc
        return desc, trace

    catalog = store.summarize_categories([it for _, _, it in pool])
    variables = {
        "item_type": item_type,
        "item_text": item_text,
        "author": author,
        "character": character_label or "(unspecified)",
        "catalog": json.dumps(catalog, ensure_ascii=False),
        "domains": ", ".join(domains or []) or "(none)",
    }
    chooser_prompt = get_text("sfx", "choose_emote", variables=variables)
    guard_prompt = get_guard("sfx", "choose_emote", variables=variables)

    steps = [_llm_step(1, "choose", "Choose emote", chooser_prompt)]
    if guard_prompt:
        steps.append(_llm_step(2, "guard", "Guard", guard_prompt))
    request = ChainJobRequest(title="SFX resolve", input=item_text,
                              llm=_resolve_llm(llm), steps=steps)

    try:
        status = create_job(_JOB_TYPE, request.model_dump(), request.input)
        job_id = status["job_id"]
        job_dir = find_job_dir(job_id)
        if job_dir is None:
            raise RuntimeError("job directory disappeared")
        await execute_chain_job(job_id, job_dir, request)
    except Exception as exc:  # noqa: BLE001
        desc = _descriptor("error", reason="resolver_failed", message=str(exc)[:200])
        trace["result"] = desc
        return desc, trace

    trace["job_id"] = job_id
    chooser_raw = _read_step_output(job_dir, "choose")
    chooser_out = _loads_object(chooser_raw) or {}
    trace["chooser"] = {"prompt_key": "sfx.choose_emote", "raw": chooser_raw, "parsed": chooser_out}

    category = (chooser_out.get("category") or "").strip().lower()
    decision = (chooser_out.get("decision") or "").strip().lower()
    if decision != "choose" or not category:
        desc = _descriptor("none", reason=chooser_out.get("reason") or "no clear emote")
        trace["result"] = desc
        return desc, trace

    # Guard verdict (the chain's final output). Absent guard → keep.
    guard_out: dict = {}
    if guard_prompt:
        guard_raw = (job_dir / "final_output.txt").read_text(encoding="utf-8") \
            if (job_dir / "final_output.txt").exists() else ""
        guard_out = _loads_object(guard_raw) or {}
        trace["guard"] = {"guard_key": "sfx.guard_emote", "raw": guard_raw, "parsed": guard_out}
    if (guard_out.get("decision") or "keep").strip().lower() == "reject":
        desc = _descriptor("rejected", reason=guard_out.get("reason") or "guard rejected",
                           candidate={"category": category,
                                      "effect_id": chooser_out.get("effect_id")})
        trace["result"] = desc
        return desc, trace

    # Weighted-random variant within the chosen category (effect_id pins one).
    effect_id = chooser_out.get("effect_id")
    candidates = [e for e in pool if e[2].category == category]
    if effect_id:
        pinned = [e for e in pool if e[2].id == effect_id]
        if pinned:
            candidates = pinned
    picked = store.weighted_choice_entry(candidates, rng=chooser)
    if picked is None:
        desc = _descriptor("none", reason=f"no items in category {category!r}")
        trace["result"] = desc
        return desc, trace

    pack_id, profile_id, item = picked
    desc = _descriptor(
        "resolved",
        effect_id=item.id,
        pack_id=pack_id,
        profile_id=profile_id,
        path=item.path,
        url=f"/v1/sfx/file/{item.path}",
        duration_ms=item.duration_ms,
        selection={
            "method": "prompt_pal",
            "prompt_key": "sfx.choose_emote",
            "guard_key": "sfx.guard_emote",
            "category": category,
            "confidence": chooser_out.get("confidence"),
            "reason": chooser_out.get("reason"),
        },
    )
    trace["result"] = desc
    return desc, trace
