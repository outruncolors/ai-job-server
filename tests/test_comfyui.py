from __future__ import annotations

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
