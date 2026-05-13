from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .config import WORKFLOWS_DIR

# Node classes that surface tunable parameters and what field names to extract
_CLASS_PARAM_MAP: dict[str, list[tuple[str, str, str]]] = {
    # class_type → [(param_name, input_field, type_hint)]
    "CLIPTextEncode": [("prompt", "text", "string")],
    "KSampler": [
        ("seed", "seed", "integer"),
        ("steps", "steps", "integer"),
        ("cfg", "cfg", "float"),
        ("sampler_name", "sampler_name", "string"),
        ("scheduler", "scheduler", "string"),
        ("denoise", "denoise", "float"),
    ],
    "KSamplerAdvanced": [
        ("seed", "noise_seed", "integer"),
        ("steps", "steps", "integer"),
        ("cfg", "cfg", "float"),
        ("sampler_name", "sampler_name", "string"),
        ("scheduler", "scheduler", "string"),
        ("add_noise", "add_noise", "string"),
    ],
    "EmptyLatentImage": [
        ("width", "width", "integer"),
        ("height", "height", "integer"),
        ("batch_size", "batch_size", "integer"),
    ],
    "EmptySD3LatentImage": [
        ("width", "width", "integer"),
        ("height", "height", "integer"),
        ("batch_size", "batch_size", "integer"),
    ],
    "CheckpointLoaderSimple": [("ckpt_name", "ckpt_name", "string")],
    "UNETLoader": [("unet_name", "unet_name", "string")],
    "LoraLoader": [
        ("lora_name", "lora_name", "string"),
        ("strength_model", "strength_model", "float"),
        ("strength_clip", "strength_clip", "float"),
    ],
    "LoadImage": [("image", "image", "string")],
    "FluxGuidance": [("guidance", "guidance", "float")],
    "BasicScheduler": [
        ("steps", "steps", "integer"),
        ("scheduler", "scheduler", "string"),
        ("denoise", "denoise", "float"),
    ],
}

# Titles containing these strings map to negative_prompt
_NEGATIVE_TITLE_HINTS = {"neg", "negative", "unconditional", "uncond"}


def _node_title(node: dict) -> str:
    return node.get("_meta", {}).get("title", "").lower()


def _is_negative_clip(node: dict) -> bool:
    title = _node_title(node)
    return any(hint in title for hint in _NEGATIVE_TITLE_HINTS)


def _sidecar_path(workflow_path: Path) -> Path:
    return workflow_path.with_suffix(".meta.json")


def introspect_params(workflow: dict) -> list[dict[str, Any]]:
    """
    Return a list of tunable params extracted from workflow node graph.
    Each param: {name, node_id, field, type, default}

    Sidecar override: if <workflow>.meta.json exists with a "params" key,
    it is used verbatim instead of auto-detection.
    """
    params: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    clip_text_nodes: list[tuple[str, dict]] = []

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if class_type == "CLIPTextEncode":
            clip_text_nodes.append((node_id, node))
            continue

        if class_type not in _CLASS_PARAM_MAP:
            continue

        for param_name, field, type_hint in _CLASS_PARAM_MAP[class_type]:
            if field not in inputs:
                continue
            raw = inputs[field]
            # Skip linked inputs (they're lists like [node_id, slot])
            if isinstance(raw, list):
                continue
            unique_name = param_name
            # Deduplicate by appending node_id suffix for repeated params
            if unique_name in seen_names:
                unique_name = f"{param_name}_{node_id}"
            seen_names.add(unique_name)
            params.append({
                "name": unique_name,
                "node_id": node_id,
                "field": field,
                "type": type_hint,
                "default": raw,
                "label": _node_title(node) or class_type,
            })

    # Handle CLIPTextEncode specially: first = prompt, others = negative_prompt
    positive_done = False
    for node_id, node in clip_text_nodes:
        inputs = node.get("inputs", {})
        text = inputs.get("text")
        if isinstance(text, list):
            continue  # linked, skip
        if _is_negative_clip(node):
            name = "negative_prompt"
        elif not positive_done:
            name = "prompt"
            positive_done = True
        else:
            name = "negative_prompt"

        if name in seen_names:
            name = f"{name}_{node_id}"
        seen_names.add(name)
        params.append({
            "name": name,
            "node_id": node_id,
            "field": "text",
            "type": "string",
            "default": text if text is not None else "",
            "label": _node_title(node) or ("Positive Prompt" if name == "prompt" else "Negative Prompt"),
        })

    return params


def load_workflow(name: str) -> dict:
    """Load a workflow JSON by name (filename without .json)."""
    path = WORKFLOWS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Workflow not found: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def inject_params(workflow: dict, overrides: dict[str, Any]) -> dict:
    """
    Return a copy of workflow with overrides applied.
    overrides: {param_name: value} — matched against the param schema.
    """
    import copy
    wf = copy.deepcopy(workflow)
    params = introspect_params(wf)
    name_to_param = {p["name"]: p for p in params}
    for name, value in overrides.items():
        if name not in name_to_param:
            continue
        p = name_to_param[name]
        wf[p["node_id"]]["inputs"][p["field"]] = value
    return wf


def list_workflows() -> list[dict[str, Any]]:
    """
    Return metadata for all workflow JSON files in WORKFLOWS_DIR.
    Checks for sidecar .meta.json to override auto-detected params.
    """
    if not WORKFLOWS_DIR.exists():
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        return []

    result = []
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        if path.stem.endswith(".meta"):
            continue
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        sidecar = _sidecar_path(path)
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                params = meta.get("params", introspect_params(workflow))
            except Exception:
                params = introspect_params(workflow)
        else:
            params = introspect_params(workflow)

        result.append({
            "name": path.stem,
            "filename": path.name,
            "params": params,
        })
    return result


def get_workflow_detail(name: str) -> Optional[dict[str, Any]]:
    workflows = list_workflows()
    for w in workflows:
        if w["name"] == name:
            return w
    return None
