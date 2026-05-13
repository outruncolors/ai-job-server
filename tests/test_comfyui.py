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
    # Re-evaluate CONFIG_PATH by reloading
    from pathlib import Path
    config_path = Path(custom)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)
    monkeypatch.setattr(cfg_mod, "_config", None)
    cfg = cfg_mod.load_config()
    assert custom.exists()
    assert cfg.port == 8188  # default


# ---------------------------------------------------------------------------
# Workflow discovery + parameterization
# ---------------------------------------------------------------------------

SAMPLE_TXT2IMG = {
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "_meta": {"title": "Load Checkpoint"},
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Prompt)"},
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


def test_introspect_params_basic():
    from app.comfyui.workflows import introspect_params
    params = introspect_params(SAMPLE_TXT2IMG)
    names = {p["name"] for p in params}
    assert "prompt" in names
    assert "negative_prompt" in names
    assert "seed" in names
    assert "steps" in names
    assert "cfg" in names
    assert "width" in names
    assert "height" in names
    assert "ckpt_name" in names


def test_introspect_params_linked_inputs_skipped():
    from app.comfyui.workflows import introspect_params
    params = introspect_params(SAMPLE_TXT2IMG)
    # "model", "positive", "negative", "latent_image" are all linked
    names = {p["name"] for p in params}
    assert "model" not in names
    assert "positive" not in names


def test_introspect_params_prompt_defaults():
    from app.comfyui.workflows import introspect_params
    params = {p["name"]: p for p in introspect_params(SAMPLE_TXT2IMG)}
    assert params["prompt"]["default"] == "beautiful landscape"
    assert params["negative_prompt"]["default"] == "ugly, blurry"
    assert params["seed"]["type"] == "integer"
    assert params["cfg"]["type"] == "float"


def test_introspect_params_negative_by_title():
    from app.comfyui.workflows import introspect_params
    # Node titled "Negative Prompt" should map to negative_prompt
    params = {p["name"]: p for p in introspect_params(SAMPLE_TXT2IMG)}
    neg = params.get("negative_prompt")
    assert neg is not None
    assert neg["default"] == "ugly, blurry"


def test_inject_params():
    from app.comfyui.workflows import inject_params, introspect_params
    overrides = {"prompt": "a red dragon", "seed": 999, "steps": 30}
    wf = inject_params(SAMPLE_TXT2IMG, overrides)
    assert wf["6"]["inputs"]["text"] == "a red dragon"
    assert wf["3"]["inputs"]["seed"] == 999
    assert wf["3"]["inputs"]["steps"] == 30
    # Unchanged
    assert wf["7"]["inputs"]["text"] == "ugly, blurry"


def test_inject_params_unknown_key_ignored():
    from app.comfyui.workflows import inject_params
    original_7_text = SAMPLE_TXT2IMG["7"]["inputs"]["text"]
    wf = inject_params(SAMPLE_TXT2IMG, {"nonexistent_key": "value"})
    assert wf["7"]["inputs"]["text"] == original_7_text


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

    (wf_dir / "txt2img.json").write_text(json.dumps(SAMPLE_TXT2IMG))

    from app.comfyui.workflows import list_workflows
    results = list_workflows()
    assert len(results) == 1
    assert results[0]["name"] == "txt2img"
    assert any(p["name"] == "prompt" for p in results[0]["params"])


def test_list_workflows_sidecar_override(tmp_path, monkeypatch):
    import app.comfyui.workflows as wf_mod
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    monkeypatch.setattr(wf_mod, "WORKFLOWS_DIR", wf_dir)

    (wf_dir / "txt2img.json").write_text(json.dumps(SAMPLE_TXT2IMG))
    custom_params = [{"name": "my_prompt", "node_id": "6", "field": "text",
                      "type": "string", "default": "", "label": "My Prompt"}]
    (wf_dir / "txt2img.meta.json").write_text(json.dumps({"params": custom_params}))

    from app.comfyui.workflows import list_workflows
    results = list_workflows()
    assert results[0]["params"] == custom_params


# ---------------------------------------------------------------------------
# Manager — adoption path (no Popen when already alive)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_adopts_when_alive():
    from app.comfyui.manager import ComfyUIManager

    manager = ComfyUIManager()
    # Pretend _is_alive returns True
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
