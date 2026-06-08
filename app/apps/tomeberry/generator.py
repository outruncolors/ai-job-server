"""Tomeberry generation pipeline — assistant requests → traced LLM turns.

``run_assistant_request`` is the heart of the app. It mirrors prattletale's
direct-executor discipline: load state → build the 14 mode variables → assemble
base+mode via Prompt Pal → render(track) → run one chain LLM step through
``app.chain.oneshot`` → parse per the mode's output_format → propose / post →
persist a rich trace + assistant message(s). It **never raises into the caller**:
on any failure it posts an error message and records the error in the trace.

The 14-variable contract lives in :func:`build_mode_variables` (pure, fully tested).
Variable *values* are self-labeling so an empty section renders to ``""`` — no
placeholder noise. Non-string carriers never reach the prompt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ...chain.models import Alternative, ChainJobRequest, ChainStep
from ...chain.oneshot import run_traced_llm
from ...chain.structured import parse_json_output
from ...llm_config import get_default_as_chain_llm_config
from ...prompt_template import render
from ...prompt_pal.service import get_text
from ...textdiff import make_proposal
from ...textdiff import store as diff_store
from . import store
from .models import HistoryEntry
from .prompts import (
    CHANGE_POLICY_TEXT,
    MODE_SPECS,
    OUTPUT_FORMAT_TEXT,
    PROMPT_VERSION,
)

JOB_TYPE = "tomeberry_request"

# output_format keys whose model output is JSON (parsed via chain.structured).
JSON_FORMATS = {"revised_text", "entity_record", "labeled_extraction", "structure_ops"}

# Conversation/context windows (keep prompts bounded on long tales).
_CONVO_WINDOW = 10
_CONTEXT_WINDOW = 8

_THE_14 = [
    "tale_title", "mode", "author_instruction", "saved_prompt", "active_pane",
    "current_structural_unit", "selected_text", "current_text", "premise",
    "project_context", "conversation_context", "request_context",
    "output_format", "change_policy",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- pure: the 14-variable contract ---------------------------------------


def build_mode_variables(
    *,
    mode: str,
    tale_title: str,
    author_instruction: str,
    saved_prompt_text: str = "",
    active_pane: str = "content",
    current_unit: Optional[dict] = None,
    selected_text: str = "",
    premise_body: str = "",
    project_context_text: str = "",
    conversation_text: str = "",
    request_descriptor: str = "",
) -> dict[str, str]:
    """Build the 14 self-labeling string variables for ``mode`` (pure).

    Every key in ``_THE_14`` is always present (empty string when absent) so the
    stage-2 renderer never literal-falls-back to a bare variable name. Sections
    carry their own label so an empty value renders to ``""``.
    """
    spec = MODE_SPECS.get(mode, {})

    def block(label: str, value: str) -> str:
        value = (value or "").strip()
        return f"{label}:\n{value}" if value else ""

    unit_line = ""
    if current_unit:
        wc = (current_unit.get("metadata") or {}).get("word_count", 0)
        unit_line = (
            f"CURRENT UNIT — {current_unit.get('type', 'unit')}: "
            f"{current_unit.get('title') or '(untitled)'} ({wc} words)"
        )

    return {
        "tale_title": tale_title or "",
        "mode": mode,
        "author_instruction": (author_instruction or "").strip(),
        "saved_prompt": block("ADDITIONAL GUIDANCE", saved_prompt_text),
        "active_pane": active_pane or "content",
        "current_structural_unit": unit_line,
        "selected_text": block("SELECTED TEXT", selected_text),
        "current_text": block("CURRENT TEXT", (current_unit or {}).get("body", "")),
        "premise": block("PREMISE", premise_body),
        "project_context": block("STORY CONTEXT", project_context_text),
        "conversation_context": block("RECENT CONVERSATION", conversation_text),
        "request_context": block("REQUEST", request_descriptor),
        "output_format": OUTPUT_FORMAT_TEXT.get(spec.get("output_format", ""), ""),
        "change_policy": CHANGE_POLICY_TEXT.get(spec.get("change_policy", ""), ""),
    }


# ---- context assembly (impure: reads the store) ---------------------------


def _render_concept_brief(c: dict) -> str:
    body = (c.get("body") or "").strip()
    if len(body) > 400:
        body = body[:400] + "…"
    return f"- [{c.get('type')}] {c.get('title') or '(untitled)'}: {body}"


def _project_context(tale_id: str, explicit_ids: list[str]) -> tuple[str, list[str]]:
    """Compact render of in-scope narrative constructs + story entities.

    Returns (rendered_text, used_concept_ids). Uses explicit ids if given, else a
    windowed slice of the tale's NCs/SEs.
    """
    concepts: list[dict] = []
    if explicit_ids:
        for cid in explicit_ids:
            c = store.get_concept(tale_id, cid)
            if c is not None:
                concepts.append(c)
    else:
        ncs = store.list_concepts(tale_id, concept_class="narrative_construct")
        ses = store.list_concepts(tale_id, concept_class="story_entity")
        # premise is already injected separately; skip it here
        ncs = [c for c in ncs if c.get("type") != "premise"]
        concepts = (ncs + ses)[:_CONTEXT_WINDOW]
    if not concepts:
        return "", []
    return "\n".join(_render_concept_brief(c) for c in concepts), [c["id"] for c in concepts]


def _conversation_context(tale_id: str) -> str:
    thread = store.get_assistant(tale_id)
    msgs = thread.get("messages", [])[-_CONVO_WINDOW:]
    lines = []
    for m in msgs:
        if m.get("role") == "marker":
            continue
        text = (m.get("text") or "").strip()
        if not text:
            continue
        who = "Author" if m.get("role") == "user" else "Tomeberry"
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def _request_descriptor(request: dict, current_unit: Optional[dict], prior: Optional[dict]) -> str:
    parts = [f"active pane: {request.get('active_pane', 'content')}"]
    scope = request.get("scope") or {}
    if scope.get("kind"):
        parts.append(f"scope: {scope['kind']}")
    if scope.get("char_range"):
        parts.append(f"char range: {scope['char_range']}")
    if current_unit:
        parts.append(f"current unit: {current_unit.get('title') or current_unit.get('id')}")
    if prior:
        parts.append("this is an iteration on a previous attempt")
    return "; ".join(parts)


# ---- parsing model output --------------------------------------------------


def _clean_prose(raw: str) -> str:
    text = (raw or "").strip()
    # strip a single wrapping code fence if present
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_output(output_format: str, raw: str) -> dict:
    """Return {kind, text, payload, error} for the mode's output_format."""
    if output_format not in JSON_FORMATS:
        return {"kind": "text", "text": _clean_prose(raw), "payload": None, "error": None}
    obj, err = parse_json_output(raw)
    if err is not None:
        return {"kind": "text", "text": _clean_prose(raw), "payload": None, "error": err}
    # extract the manuscript text for revised_text-style outputs
    text = None
    if isinstance(obj, dict) and "revised_text" in obj:
        text = obj.get("revised_text")
    return {"kind": "json", "text": text, "payload": obj, "error": None}


# ---- the pipeline ----------------------------------------------------------


async def run_assistant_request(tale_id: str, request: dict) -> dict:
    """Run one assistant request end-to-end. Returns a result dict for the route.

    Shape: {request_id, job_id, mode, messages: [assistant message dict, ...],
    proposal: {...}|None, error: str|None}. Never raises.
    """
    request_id = store.new_request_id()
    at = _now()
    tale = store.get_tale(tale_id)
    if tale is None:
        return {"error": "tale not found", "request_id": request_id, "messages": []}

    mode = (request.get("mode") or tale.get("default_mode") or "draft").lower()
    if mode not in MODE_SPECS:
        mode = "draft"
    spec = MODE_SPECS[mode]
    active_pane = request.get("active_pane") or "content"
    author_text = (request.get("text") or "").strip()
    saved_prompt_key = request.get("saved_prompt_key") or tale.get("default_saved_prompt")
    scope = request.get("scope") or {}
    selected_text = scope.get("selected_text") or ""
    current_unit_id = request.get("current_unit_id")
    current_unit = store.get_concept(tale_id, current_unit_id) if current_unit_id else None

    # Iterate: thread prior attempt + feedback into the instruction.
    prior = None
    iterate_of = request.get("iterate_of")
    if iterate_of:
        prior = store.get_trace(tale_id, iterate_of)
        if prior:
            prior_after = ((prior.get("proposal") or {}).get("after")) or prior.get("raw_model_output", "")
            author_text = (
                f"Your previous attempt was:\n{prior_after}\n\n"
                f"The author's feedback / new instruction:\n{author_text}"
            )

    # Post the author's message first (chat-visible).
    user_msg = None
    if request.get("text"):
        user_msg = {
            "id": store.new_message_id(),
            "role": "user",
            "kind": "chat",
            "text": request.get("text"),
            "at": at,
            "mode": mode,
            "request_id": request_id,
        }
        store.append_assistant_message(tale_id, user_msg)

    # Build context.
    premise_body = ""
    if tale.get("premise_id"):
        pc = store.get_concept(tale_id, tale["premise_id"])
        premise_body = (pc or {}).get("body", "")
    project_text, context_ids = _project_context(tale_id, request.get("context_concept_ids") or [])
    convo_text = _conversation_context(tale_id)
    saved_prompt_text = ""
    if saved_prompt_key:
        try:
            saved_prompt_text = get_text("tomeberry", saved_prompt_key)
        except Exception:
            saved_prompt_text = ""
    request_desc = _request_descriptor(request, current_unit, prior)

    bundle = build_mode_variables(
        mode=mode,
        tale_title=tale.get("title", ""),
        author_instruction=author_text or "Proceed.",
        saved_prompt_text=saved_prompt_text,
        active_pane=active_pane,
        current_unit=current_unit,
        selected_text=selected_text,
        premise_body=premise_body,
        project_context_text=project_text,
        conversation_text=convo_text,
        request_descriptor=request_desc,
    )

    # Assemble base + mode WITHOUT filling vars (so render() does it + tracks).
    unresolved = (
        get_text("tomeberry", "base")
        + "\n\n"
        + get_text("tomeberry", f"mode.{mode}")
    )
    rendered = render(unresolved, variables=bundle, final=True, track=True)
    resolved_prompt = rendered.text

    trace: dict[str, Any] = {
        "request_id": request_id,
        "tale_id": tale_id,
        "at": at,
        "mode": mode,
        "saved_prompt_key": saved_prompt_key,
        "prompt_version": PROMPT_VERSION,
        "active_pane": active_pane,
        "current_structural_unit": current_unit_id,
        "scope": scope,
        "resolved_variables": bundle,
        "variable_substitutions": [{"token": s.token, "value": s.value} for s in rendered.substitutions],
        "context_concept_ids": context_ids,
        "unresolved_template": unresolved,
        "resolved_prompt": resolved_prompt,
        "iterate_of": iterate_of,
        "user_action": "pending",
    }

    # Execute.
    try:
        step = ChainStep(
            number=1,
            id="turn",
            name=mode.capitalize(),
            type="llm",
            alternatives=[
                Alternative(prompt=resolved_prompt, tools=list(spec.get("mcp_tools") or []), thinking=False)
            ],
        )
        req = ChainJobRequest(
            title=f"Tomeberry {mode}",
            input=author_text or "Proceed.",
            llm=get_default_as_chain_llm_config(),
            steps=[step],
        )
        result = await run_traced_llm(JOB_TYPE, req, extra_meta={"app": "tomeberry", "tale_id": tale_id})
        raw = result.final_output
        trace["job_id"] = result.job_id
        trace["steps"] = result.steps
        trace["raw_model_output"] = raw
        trace["mcp_tool_calls"] = _read_tool_calls(result)
    except Exception as exc:  # never crash the turn
        trace["error"] = str(exc)
        store.write_trace(tale_id, request_id, trace)
        err_msg = {
            "id": store.new_message_id(),
            "role": "assistant",
            "kind": "status",
            "text": f"⚠️ generation failed: {exc}",
            "at": _now(),
            "mode": mode,
            "request_id": request_id,
        }
        store.append_assistant_message(tale_id, err_msg)
        return {"request_id": request_id, "mode": mode, "messages": [m for m in (user_msg, err_msg) if m], "error": str(exc)}

    parsed = _parse_output(spec["output_format"], raw)
    trace["parsed"] = {"output_format": spec["output_format"], "kind": parsed["kind"], "payload": parsed["payload"], "parse_error": parsed["error"]}

    # Propose / post.
    proposal_ref, proposal_obj, assistant_text = _make_proposal_for_mode(
        tale_id, mode, spec, parsed, current_unit, selected_text, request_id
    )
    if proposal_obj is not None:
        trace["proposal"] = {
            "diff_id": proposal_obj.id,
            "target_concept_id": current_unit_id,
            "before": proposal_obj.before,
            "after": proposal_obj.after,
        }
    elif proposal_ref is not None:
        trace["proposal"] = {"payload": proposal_ref.get("proposal", {}).get("payload")}

    assistant_msg = {
        "id": store.new_message_id(),
        "role": "assistant",
        "kind": "proposal" if proposal_ref else "chat",
        "text": assistant_text,
        "at": _now(),
        "mode": mode,
        "saved_prompt_key": saved_prompt_key,
        "request_id": request_id,
        "context_refs": context_ids,
    }
    if proposal_ref:
        assistant_msg["proposal"] = proposal_ref["proposal"]
    store.append_assistant_message(tale_id, assistant_msg)

    # record proposed history on the target concept
    if proposal_obj is not None and current_unit_id:
        store.update_concept(
            tale_id,
            current_unit_id,
            {},
            history=HistoryEntry(
                at=_now(), kind="proposed", request_id=request_id, mode=mode,
                diff_id=proposal_obj.id, summary=f"{mode} proposal",
            ),
        )

    store.write_trace(tale_id, request_id, trace)
    return {
        "request_id": request_id,
        "job_id": trace.get("job_id"),
        "mode": mode,
        "messages": [m for m in (user_msg, assistant_msg) if m],
        "proposal": assistant_msg.get("proposal"),
        "error": None,
    }


def _read_tool_calls(result) -> list[dict]:
    """Best-effort: read the chain step's tool_calls.json if the executor wrote one."""
    if result.job_dir is None:
        return []
    import json

    out: list[dict] = []
    steps_dir = result.job_dir / "steps"
    if steps_dir.is_dir():
        for f in steps_dir.glob("*/tool_calls.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    out.extend(data)
            except (OSError, ValueError):
                continue
    return out


def _make_proposal_for_mode(
    tale_id: str,
    mode: str,
    spec: dict,
    parsed: dict,
    current_unit: Optional[dict],
    selected_text: str,
    request_id: str,
):
    """Return (proposal_ref|None, textdiff Proposal|None, assistant_text)."""
    proposes = spec.get("proposes")
    scope_key = f"{tale_id}/{(current_unit or {}).get('id', 'tale')}"

    if proposes == "manuscript_diff":
        after = parsed.get("text")
        if after is None and parsed["kind"] == "text":
            after = parsed.get("text")
        if not after:
            return None, None, "(the model returned no usable text)"
        before = selected_text or (current_unit or {}).get("body", "")
        proposal = make_proposal(before, after, mode="replace")
        diff_store.save_proposal("tomeberry", scope_key, proposal)
        ref = {
            "proposal": {
                "diff_id": proposal.id,
                "scope": {"kind": "selection" if selected_text else "unit"},
                "status": "pending",
                "target_concept_id": (current_unit or {}).get("id"),
            }
        }
        summary = ""
        if isinstance(parsed.get("payload"), dict):
            summary = parsed["payload"].get("summary") or ""
        return ref, proposal, summary or "Proposed an edit — review the diff."

    if proposes in ("concept_upsert", "concept_creates"):
        payload = parsed.get("payload")
        ref = {
            "proposal": {
                "diff_id": f"concept_{request_id}",
                "scope": {"kind": "concept"},
                "status": "pending",
                "payload": payload,
            }
        }
        n = 1
        if isinstance(payload, dict) and isinstance(payload.get("concepts"), list):
            n = len(payload["concepts"])
        return ref, None, f"Proposed {n} concept record(s) — accept to add them."

    if proposes == "structure_ops":
        payload = parsed.get("payload")
        if not payload:
            return None, None, _chat_text(parsed)
        ref = {
            "proposal": {
                "diff_id": f"ops_{request_id}",
                "scope": {"kind": "structure"},
                "status": "pending",
                "payload": payload,
            }
        }
        ops = payload.get("ops", []) if isinstance(payload, dict) else []
        return ref, None, f"Proposed {len(ops)} structural operation(s)."

    # chat / explain-only
    return None, None, _chat_text(parsed)


def _chat_text(parsed: dict) -> str:
    if parsed.get("kind") == "text":
        return parsed.get("text") or "(no response)"
    import json

    return json.dumps(parsed.get("payload"), indent=2) if parsed.get("payload") else "(no response)"
