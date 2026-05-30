from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

from .config import WORKFLOWS_DIR

_PROMPT_TITLE = "PROMPT"
_REF_IMAGE_TITLES: tuple[str, ...] = ("REF_IMAGE_1", "REF_IMAGE_2")
_SEED_TITLE = "SEED"
_SEED_CLASS = "PrimitiveInt"
_DENOISE_TITLE = "DENOISE"
_DENOISE_CLASS = "PrimitiveFloat"


def find_prompt_node(workflow: dict) -> Optional[tuple[str, dict]]:
    """Return (node_id, node) for the single node titled PROMPT, or None."""
    found = [
        (nid, node)
        for nid, node in workflow.items()
        if isinstance(node, dict) and node.get("_meta", {}).get("title") == _PROMPT_TITLE
    ]
    if len(found) == 1:
        return found[0]
    return None


def validate_workflow(workflow: dict) -> Optional[str]:
    """Return an error string if the workflow is not compatible, else None."""
    matches = [
        (nid, node)
        for nid, node in workflow.items()
        if isinstance(node, dict) and node.get("_meta", {}).get("title") == _PROMPT_TITLE
    ]
    if not matches:
        return (
            f'No node titled "{_PROMPT_TITLE}" — rename your prompt text node '
            f'to {_PROMPT_TITLE} in ComfyUI and re-export in API format'
        )
    if len(matches) > 1:
        return (
            f'Multiple nodes titled "{_PROMPT_TITLE}" — workflow must contain exactly one'
        )
    node_id, node = matches[0]
    if "text" not in node.get("inputs", {}):
        return (
            f'Node titled "{_PROMPT_TITLE}" has no "text" input — '
            f'it must be a text prompt node (e.g. CLIPTextEncode)'
        )
    return None


def inject_prompt(workflow: dict, prompt: str) -> dict:
    """Return a deep copy of workflow with the PROMPT node's text replaced."""
    err = validate_workflow(workflow)
    if err:
        raise ValueError(err)
    result = copy.deepcopy(workflow)
    node_id, _ = find_prompt_node(result)
    result[node_id]["inputs"]["text"] = prompt
    return result


def find_image_param_nodes(workflow: dict) -> dict[str, str]:
    """Return {title: node_id} for known REF_IMAGE_* LoadImage nodes.

    Skips titles that appear more than once or whose node isn't a LoadImage
    with a replaceable `image` input — the workflow stays valid, those fields
    just don't get exposed.
    """
    by_title: dict[str, list[str]] = {t: [] for t in _REF_IMAGE_TITLES}
    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        title = node.get("_meta", {}).get("title")
        if title not in by_title:
            continue
        if node.get("class_type") != "LoadImage":
            continue
        if "image" not in node.get("inputs", {}):
            continue
        by_title[title].append(nid)
    return {title: ids[0] for title, ids in by_title.items() if len(ids) == 1}


def inject_image_param(workflow: dict, title: str, filename: str) -> dict:
    """Return a deep copy with the named LoadImage node's `image` set to filename.

    Unknown titles raise ValueError so callers can surface bad input.
    """
    found = find_image_param_nodes(workflow)
    if title not in found:
        raise ValueError(f'Workflow has no LoadImage node titled "{title}"')
    result = copy.deepcopy(workflow)
    result[found[title]]["inputs"]["image"] = filename
    return result


def find_value_param_node(
    workflow: dict, title: str, class_type: str
) -> Optional[str]:
    """Return the node id of the single node titled `title` with the given
    `class_type` and a replaceable `value` input, or None.

    Skips titles that appear zero times or more than once, or whose node isn't
    the expected primitive — the workflow stays valid, the field just isn't
    exposed (mirrors `find_image_param_nodes`).
    """
    matches = [
        nid
        for nid, node in workflow.items()
        if isinstance(node, dict)
        and node.get("_meta", {}).get("title") == title
        and node.get("class_type") == class_type
        and "value" in node.get("inputs", {})
    ]
    return matches[0] if len(matches) == 1 else None


def find_seed_node(workflow: dict) -> Optional[str]:
    """Return the node id of the SEED PrimitiveInt node, or None."""
    return find_value_param_node(workflow, _SEED_TITLE, _SEED_CLASS)


def find_denoise_node(workflow: dict) -> Optional[str]:
    """Return the node id of the DENOISE PrimitiveFloat node, or None."""
    return find_value_param_node(workflow, _DENOISE_TITLE, _DENOISE_CLASS)


def inject_seed(workflow: dict, value: int) -> dict:
    """Return a deep copy with the SEED node's `value` set to an integer."""
    node_id = find_seed_node(workflow)
    if node_id is None:
        raise ValueError(f'Workflow has no {_SEED_CLASS} node titled "{_SEED_TITLE}"')
    result = copy.deepcopy(workflow)
    result[node_id]["inputs"]["value"] = value
    return result


def inject_denoise(workflow: dict, value: float) -> dict:
    """Return a deep copy with the DENOISE node's `value` set to a float."""
    node_id = find_denoise_node(workflow)
    if node_id is None:
        raise ValueError(
            f'Workflow has no {_DENOISE_CLASS} node titled "{_DENOISE_TITLE}"'
        )
    result = copy.deepcopy(workflow)
    result[node_id]["inputs"]["value"] = value
    return result


def load_workflow(name: str) -> dict:
    """Load a workflow JSON by name (filename without .json)."""
    path = WORKFLOWS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Workflow not found: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_workflows() -> list[dict[str, Any]]:
    """Return identity + validity info for all workflow JSON files."""
    if not WORKFLOWS_DIR.exists():
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        return []

    result = []
    for path in sorted(WORKFLOWS_DIR.glob("*.json")):
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        err = validate_workflow(workflow)
        prompt_node = find_prompt_node(workflow)
        image_params = find_image_param_nodes(workflow)
        result.append({
            "name": path.stem,
            "filename": path.name,
            "valid": err is None,
            "promptNodeId": prompt_node[0] if prompt_node else None,
            "imageParams": [
                {"name": title, "nodeId": image_params[title]}
                for title in _REF_IMAGE_TITLES
                if title in image_params
            ],
            "seedNodeId": find_seed_node(workflow),
            "denoiseNodeId": find_denoise_node(workflow),
            "error": err,
        })
    return result
