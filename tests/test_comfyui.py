from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_comfyui_config_defaults(tmp_path, monkeypatch):
    import app.comfyui.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "comfyui.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    config = cfg_mod.load_config()
    assert config.port == 8188
    assert config.autostart is True
    assert config.use_sage_attention is True
    assert config.vram_mode == "highvram"
    assert (tmp_path / "comfyui.json").exists()


def test_comfyui_config_roundtrip(tmp_path, monkeypatch):
    import app.comfyui.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "comfyui.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    from app.comfyui.config import ComfyUIConfig
    original = ComfyUIConfig(port=9999, autostart=False, use_sage_attention=False)
    cfg_mod.save_config(original)
    monkeypatch.setattr(cfg_mod, "_config", None)
    reloaded = cfg_mod.load_config()
    assert reloaded.port == 9999
    assert reloaded.autostart is False


def test_comfyui_config_env_var(tmp_path, monkeypatch):
    custom = tmp_path / "custom_comfy.json"
    monkeypatch.setenv("COMFYUI_CONFIG_PATH", str(custom))
    import importlib
    import app.comfyui.config as cfg_mod
    from pathlib import Path
    config_path = Path(custom)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)
    monkeypatch.setattr(cfg_mod, "_config", None)
    cfg = cfg_mod.load_config()
    assert custom.exists()
    assert cfg.port == 8188  # default


# ---------------------------------------------------------------------------
# Workflow validation + prompt injection
# ---------------------------------------------------------------------------

SAMPLE_WORKFLOW_VALID = {
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "_meta": {"title": "Load Checkpoint"},
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "PROMPT"},
        "inputs": {"text": "beautiful landscape", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "Negative Prompt"},
        "inputs": {"text": "ugly, blurry", "clip": ["4", 1]},
    },
    "3": {
        "class_type": "KSampler",
        "_meta": {"title": "KSampler"},
        "inputs": {
            "seed": 42,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "_meta": {"title": "Empty Latent Image"},
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
}


def test_validate_workflow_valid():
    from app.comfyui.workflows import validate_workflow
    assert validate_workflow(SAMPLE_WORKFLOW_VALID) is None


def test_validate_workflow_missing_prompt_node():
    from app.comfyui.workflows import validate_workflow
    wf = {
        "6": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive"}, "inputs": {"text": "hi"}},
    }
    err = validate_workflow(wf)
    assert err is not None
    assert "PROMPT" in err


def test_validate_workflow_multiple_prompt_nodes():
    from app.comfyui.workflows import validate_workflow
    wf = {
        "6": {"class_type": "CLIPTextEncode", "_meta": {"title": "PROMPT"}, "inputs": {"text": "hi"}},
        "7": {"class_type": "CLIPTextEncode", "_meta": {"title": "PROMPT"}, "inputs": {"text": "bye"}},
    }
    err = validate_workflow(wf)
    assert err is not None
    assert "exactly one" in err


def test_validate_workflow_prompt_node_no_text_input():
    from app.comfyui.workflows import validate_workflow
    wf = {
        "6": {"class_type": "SomeNode", "_meta": {"title": "PROMPT"}, "inputs": {"other": "value"}},
    }
    err = validate_workflow(wf)
    assert err is not None
    assert "text" in err


def test_find_prompt_node():
    from app.comfyui.workflows import find_prompt_node
    result = find_prompt_node(SAMPLE_WORKFLOW_VALID)
    assert result is not None
    node_id, node = result
    assert node_id == "6"
    assert node["_meta"]["title"] == "PROMPT"


def test_inject_prompt():
    from app.comfyui.workflows import inject_prompt
    wf = inject_prompt(SAMPLE_WORKFLOW_VALID, "a red dragon")
    assert wf["6"]["inputs"]["text"] == "a red dragon"
    # Original untouched
    assert SAMPLE_WORKFLOW_VALID["6"]["inputs"]["text"] == "beautiful landscape"
    # Negative prompt untouched
    assert wf["7"]["inputs"]["text"] == "ugly, blurry"


def test_inject_prompt_invalid_workflow():
    from app.comfyui.workflows import inject_prompt
    wf = {"6": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive"}, "inputs": {"text": "hi"}}}
    with pytest.raises(ValueError, match="PROMPT"):
        inject_prompt(wf, "test")


def test_list_workflows_empty(tmp_path, monkeypatch):
    import app.comfyui.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "WORKFLOWS_DIR", tmp_path / "workflows")
    import app.comfyui.workflows as wf_mod
    monkeypatch.setattr(wf_mod, "WORKFLOWS_DIR", tmp_path / "workflows")

    from app.comfyui.workflows import list_workflows
    result = list_workflows()
    assert result == []
    assert (tmp_path / "workflows").is_dir()


def test_list_workflows_finds_json(tmp_path, monkeypatch):
    import app.comfyui.workflows as wf_mod
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    monkeypatch.setattr(wf_mod, "WORKFLOWS_DIR", wf_dir)

    (wf_dir / "txt2img.json").write_text(json.dumps(SAMPLE_WORKFLOW_VALID))

    from app.comfyui.workflows import list_workflows
    results = list_workflows()
    assert len(results) == 1
    assert results[0]["name"] == "txt2img"
    assert results[0]["valid"] is True
    assert results[0]["promptNodeId"] == "6"
    assert results[0]["error"] is None


SAMPLE_WORKFLOW_WITH_REFS = {
    "76": {
        "class_type": "LoadImage",
        "_meta": {"title": "REF_IMAGE_1"},
        "inputs": {"image": "default1.png"},
    },
    "81": {
        "class_type": "LoadImage",
        "_meta": {"title": "REF_IMAGE_2"},
        "inputs": {"image": "default2.png"},
    },
    "99": {
        "class_type": "LoadImage",
        "_meta": {"title": "RANDOM"},
        "inputs": {"image": "ignored.png"},
    },
    "135": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "PROMPT"},
        "inputs": {"text": "edit me"},
    },
}


def test_find_image_param_nodes_picks_up_known_titles():
    from app.comfyui.workflows import find_image_param_nodes
    result = find_image_param_nodes(SAMPLE_WORKFLOW_WITH_REFS)
    assert result == {"REF_IMAGE_1": "76", "REF_IMAGE_2": "81"}


def test_find_image_param_nodes_empty_on_t2i():
    from app.comfyui.workflows import find_image_param_nodes
    assert find_image_param_nodes(SAMPLE_WORKFLOW_VALID) == {}


def test_find_image_param_nodes_skips_duplicates():
    from app.comfyui.workflows import find_image_param_nodes
    wf = {
        "a": {"class_type": "LoadImage", "_meta": {"title": "REF_IMAGE_1"}, "inputs": {"image": "x.png"}},
        "b": {"class_type": "LoadImage", "_meta": {"title": "REF_IMAGE_1"}, "inputs": {"image": "y.png"}},
    }
    assert find_image_param_nodes(wf) == {}


def test_find_image_param_nodes_skips_non_loadimage():
    from app.comfyui.workflows import find_image_param_nodes
    wf = {
        "a": {"class_type": "SomeOtherNode", "_meta": {"title": "REF_IMAGE_1"}, "inputs": {"image": "x.png"}},
    }
    assert find_image_param_nodes(wf) == {}


def test_inject_image_param_writes_filename():
    from app.comfyui.workflows import inject_image_param
    wf = inject_image_param(SAMPLE_WORKFLOW_WITH_REFS, "REF_IMAGE_1", "uploaded.png")
    assert wf["76"]["inputs"]["image"] == "uploaded.png"
    # Other ref untouched
    assert wf["81"]["inputs"]["image"] == "default2.png"
    # Original untouched
    assert SAMPLE_WORKFLOW_WITH_REFS["76"]["inputs"]["image"] == "default1.png"


def test_inject_image_param_unknown_title():
    from app.comfyui.workflows import inject_image_param
    with pytest.raises(ValueError, match="REF_IMAGE_2"):
        inject_image_param(SAMPLE_WORKFLOW_VALID, "REF_IMAGE_2", "x.png")


def test_list_workflows_includes_image_params(tmp_path, monkeypatch):
    import app.comfyui.workflows as wf_mod
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    monkeypatch.setattr(wf_mod, "WORKFLOWS_DIR", wf_dir)
    (wf_dir / "t2i.json").write_text(json.dumps(SAMPLE_WORKFLOW_VALID))
    (wf_dir / "edit.json").write_text(json.dumps(SAMPLE_WORKFLOW_WITH_REFS))

    from app.comfyui.workflows import list_workflows
    by_name = {w["name"]: w for w in list_workflows()}
    assert by_name["t2i"]["imageParams"] == []
    assert by_name["edit"]["imageParams"] == [
        {"name": "REF_IMAGE_1", "nodeId": "76"},
        {"name": "REF_IMAGE_2", "nodeId": "81"},
    ]


def test_list_workflows_invalid_workflow(tmp_path, monkeypatch):
    import app.comfyui.workflows as wf_mod
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    monkeypatch.setattr(wf_mod, "WORKFLOWS_DIR", wf_dir)

    wf_no_prompt = {"6": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive"}, "inputs": {"text": "hi"}}}
    (wf_dir / "bad.json").write_text(json.dumps(wf_no_prompt))

    from app.comfyui.workflows import list_workflows
    results = list_workflows()
    assert results[0]["valid"] is False
    assert results[0]["promptNodeId"] is None
    assert results[0]["error"] is not None


# ---------------------------------------------------------------------------
# SEED + DENOISE param nodes
# ---------------------------------------------------------------------------

SAMPLE_WORKFLOW_SEED_DENOISE = {
    "133": {
        "class_type": "PrimitiveInt",
        "_meta": {"title": "SEED"},
        "inputs": {"value": 1337},
    },
    "140": {
        "class_type": "PrimitiveFloat",
        "_meta": {"title": "DENOISE"},
        "inputs": {"value": 0.8},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "PROMPT"},
        "inputs": {"text": "hi"},
    },
}


def test_find_seed_and_denoise_nodes():
    from app.comfyui.workflows import find_seed_node, find_denoise_node
    assert find_seed_node(SAMPLE_WORKFLOW_SEED_DENOISE) == "133"
    assert find_denoise_node(SAMPLE_WORKFLOW_SEED_DENOISE) == "140"


def test_find_seed_denoise_absent():
    from app.comfyui.workflows import find_seed_node, find_denoise_node
    assert find_seed_node(SAMPLE_WORKFLOW_VALID) is None
    assert find_denoise_node(SAMPLE_WORKFLOW_VALID) is None


def test_find_value_param_node_skips_wrong_class():
    from app.comfyui.workflows import find_seed_node
    # Right title, wrong class_type → not exposed.
    wf = {"1": {"class_type": "KSampler", "_meta": {"title": "SEED"}, "inputs": {"value": 1}}}
    assert find_seed_node(wf) is None


def test_find_value_param_node_skips_duplicates():
    from app.comfyui.workflows import find_seed_node
    wf = {
        "1": {"class_type": "PrimitiveInt", "_meta": {"title": "SEED"}, "inputs": {"value": 1}},
        "2": {"class_type": "PrimitiveInt", "_meta": {"title": "SEED"}, "inputs": {"value": 2}},
    }
    assert find_seed_node(wf) is None


def test_inject_seed_and_denoise():
    from app.comfyui.workflows import inject_seed, inject_denoise
    wf = inject_seed(SAMPLE_WORKFLOW_SEED_DENOISE, 18446744073709551615)
    assert wf["133"]["inputs"]["value"] == 18446744073709551615
    wf = inject_denoise(wf, 0.42)
    assert wf["140"]["inputs"]["value"] == 0.42
    # Original untouched
    assert SAMPLE_WORKFLOW_SEED_DENOISE["133"]["inputs"]["value"] == 1337
    assert SAMPLE_WORKFLOW_SEED_DENOISE["140"]["inputs"]["value"] == 0.8


def test_inject_seed_absent_raises():
    from app.comfyui.workflows import inject_seed
    with pytest.raises(ValueError, match="SEED"):
        inject_seed(SAMPLE_WORKFLOW_VALID, 5)


def test_list_workflows_includes_seed_denoise(tmp_path, monkeypatch):
    import app.comfyui.workflows as wf_mod
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    monkeypatch.setattr(wf_mod, "WORKFLOWS_DIR", wf_dir)
    (wf_dir / "t2i.json").write_text(json.dumps(SAMPLE_WORKFLOW_VALID))
    (wf_dir / "i2i.json").write_text(json.dumps(SAMPLE_WORKFLOW_SEED_DENOISE))

    from app.comfyui.workflows import list_workflows
    by_name = {w["name"]: w for w in list_workflows()}
    assert by_name["t2i"]["seedNodeId"] is None
    assert by_name["t2i"]["denoiseNodeId"] is None
    assert by_name["i2i"]["seedNodeId"] == "133"
    assert by_name["i2i"]["denoiseNodeId"] == "140"


# ---------------------------------------------------------------------------
# ImageJobRequest — seed string validation
# ---------------------------------------------------------------------------

def test_image_request_seed_accepts_big_digit_string():
    from app.models import ImageJobRequest
    req = ImageJobRequest(workflow="w", prompt="p", seed="18446744073709551615")
    assert req.seed == "18446744073709551615"


def test_image_request_seed_empty_becomes_none():
    from app.models import ImageJobRequest
    assert ImageJobRequest(workflow="w", prompt="p", seed="").seed is None


def test_image_request_seed_rejects_non_digits():
    from app.models import ImageJobRequest
    with pytest.raises(ValueError):
        ImageJobRequest(workflow="w", prompt="p", seed="-5")
    with pytest.raises(ValueError):
        ImageJobRequest(workflow="w", prompt="p", seed="abc")


def test_image_request_denoise_bounds():
    from app.models import ImageJobRequest
    assert ImageJobRequest(workflow="w", prompt="p", denoise=0.5).denoise == 0.5
    with pytest.raises(ValueError):
        ImageJobRequest(workflow="w", prompt="p", denoise=1.5)


# ---------------------------------------------------------------------------
# Runner — seed selection branch (randomize / explicit / default)
# ---------------------------------------------------------------------------

def _resolved_workflow_after_run(tmp_path, monkeypatch, request_obj):
    """Run execute_image_job with a fully mocked ComfyUI and return the
    resolved workflow.json the runner wrote to job_dir."""
    import app.comfyui.runner as runner_mod

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "status.json").write_text(json.dumps({"status": "queued"}))
    (job_dir / "artifacts.json").write_text(json.dumps([]))

    monkeypatch.setattr(runner_mod, "load_workflow", lambda name: copy.deepcopy(SAMPLE_WORKFLOW_SEED_DENOISE))

    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(runner_mod.asyncio, "sleep", _no_sleep)

    mock_client = MagicMock()
    mock_client.submit = AsyncMock(return_value={"prompt_id": "pid1"})
    mock_client.history = AsyncMock(return_value={
        "pid1": {"outputs": {"9": {"images": [{"filename": "out.png"}]}}, "status": {}},
    })
    mock_client.fetch_view = AsyncMock(return_value=b"PNGDATA")
    monkeypatch.setattr(runner_mod, "ComfyUIClient", lambda url: mock_client)

    manager = MagicMock()
    manager._is_alive = AsyncMock(return_value=True)
    config = MagicMock(host="127.0.0.1", port=8188, autostart=False)

    import asyncio as _aio
    _aio.run(
        runner_mod.execute_image_job("job1", job_dir, request_obj, config, manager)
    )
    return json.loads((job_dir / "workflow.json").read_text())


def test_runner_randomize_seed_in_range(tmp_path, monkeypatch):
    import app.comfyui.runner as runner_mod
    monkeypatch.setattr(runner_mod.random, "randint", lambda lo, hi: hi)  # max seed
    from app.models import ImageJobRequest
    req = ImageJobRequest(workflow="i2i", prompt="p", randomize_seed=True)
    wf = _resolved_workflow_after_run(tmp_path, monkeypatch, req)
    assert wf["133"]["inputs"]["value"] == 2**64 - 1


def test_runner_explicit_seed(tmp_path, monkeypatch):
    from app.models import ImageJobRequest
    req = ImageJobRequest(workflow="i2i", prompt="p", seed="12345", denoise=0.3)
    wf = _resolved_workflow_after_run(tmp_path, monkeypatch, req)
    assert wf["133"]["inputs"]["value"] == 12345
    assert wf["140"]["inputs"]["value"] == 0.3


def test_runner_default_seed_untouched(tmp_path, monkeypatch):
    from app.models import ImageJobRequest
    req = ImageJobRequest(workflow="i2i", prompt="p")  # no seed, no randomize
    wf = _resolved_workflow_after_run(tmp_path, monkeypatch, req)
    assert wf["133"]["inputs"]["value"] == 1337  # workflow default


# ---------------------------------------------------------------------------
# Manager — adoption path (no Popen when already alive)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_adopts_when_alive():
    from app.comfyui.manager import ComfyUIManager

    manager = ComfyUIManager()
    manager._is_alive = AsyncMock(return_value=True)
    manager._find_pid_on_port = MagicMock(return_value=1234)
    manager.status = AsyncMock(return_value={"running": True, "pid": 1234})

    with patch("subprocess.Popen") as mock_popen:
        await manager.start()
        mock_popen.assert_not_called()

    assert manager._adopted_pid == 1234


# ---------------------------------------------------------------------------
# Router — status endpoint (mocked manager)
# ---------------------------------------------------------------------------

def test_comfyui_status_route(client, monkeypatch):
    import app.comfyui.router as router_mod
    mock_mgr = MagicMock()
    mock_mgr.status = AsyncMock(return_value={
        "running": False, "pid": None, "uptime_seconds": None,
        "port": 8188, "gpu": None, "queue_remaining": 0,
    })
    monkeypatch.setattr(router_mod, "get_manager", lambda: mock_mgr)

    r = client.get("/v1/comfyui/status")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is False
    assert body["port"] == 8188


def test_comfyui_workflows_route(client, monkeypatch, tmp_path):
    import app.comfyui.router as router_mod
    import app.comfyui.workflows as wf_mod
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    monkeypatch.setattr(wf_mod, "WORKFLOWS_DIR", wf_dir)

    r = client.get("/v1/comfyui/workflows")
    assert r.status_code == 200
    assert r.json() == {"workflows": []}


def test_comfyui_config_route(client):
    r = client.get("/v1/comfyui/config")
    assert r.status_code == 200
    body = r.json()
    assert "port" in body
    assert "autostart" in body
    assert "vram_mode" in body
