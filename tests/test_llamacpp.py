from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_llamacpp_config_defaults(tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    cfg = cfg_mod.load_config()
    assert cfg.port == 8080
    assert cfg.binary_path.endswith("llama-server")
    assert cfg.models_dir == "/opt/ai-stack/models"
    assert cfg.default_preset is None
    assert (tmp_path / "llamacpp.json").exists()


def test_llamacpp_config_roundtrip(tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    from app.llamacpp.config import LlamaCppConfig
    original = LlamaCppConfig(port=9999, default_preset="gemma-3", models_dir="/tmp/models")
    cfg_mod.save_config(original)
    monkeypatch.setattr(cfg_mod, "_config", None)
    reloaded = cfg_mod.load_config()
    assert reloaded.port == 9999
    assert reloaded.default_preset == "gemma-3"
    assert reloaded.models_dir == "/tmp/models"


# ---------------------------------------------------------------------------
# Args + hashing
# ---------------------------------------------------------------------------

def test_args_from_preset_translates_keys(tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    from app.llamacpp.manager import LlamaCppManager
    mgr = LlamaCppManager()
    preset = {
        "model_path": "/models/g.gguf",
        "args": {
            "ctx_size": 32768,
            "n_gpu_layers": 99,
            "flash_attn": True,
            "verbose": False,  # excluded
            "mmproj": None,    # excluded
        },
    }
    argv = mgr._args_from_preset(preset)
    assert argv[0].endswith("llama-server")
    assert "--model" in argv and "/models/g.gguf" in argv
    assert "--host" in argv and "127.0.0.1" in argv
    assert "--port" in argv and "8080" in argv
    assert "--ctx-size" in argv and "32768" in argv
    assert "--n-gpu-layers" in argv and "99" in argv
    assert "--flash-attn" in argv
    assert "--verbose" not in argv
    assert "--mmproj" not in argv


def test_stable_hash_is_order_independent():
    from app.llamacpp.manager import _stable_hash
    a = {"model_path": "/x.gguf", "args": {"ctx_size": 4096, "n_gpu_layers": 99}}
    b = {"args": {"n_gpu_layers": 99, "ctx_size": 4096}, "model_path": "/x.gguf"}
    assert _stable_hash(a) == _stable_hash(b)


def test_stable_hash_changes_with_args():
    from app.llamacpp.manager import _stable_hash
    base = {"model_path": "/x.gguf", "args": {"ctx_size": 4096}}
    bigger = {"model_path": "/x.gguf", "args": {"ctx_size": 8192}}
    assert _stable_hash(base) != _stable_hash(bigger)


# ---------------------------------------------------------------------------
# ensure_loaded short-circuits on hash match
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_loaded_noop_when_hash_matches(tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    from app.llamacpp.manager import LlamaCppManager, _stable_hash
    mgr = LlamaCppManager()
    preset = {"model_path": "/x.gguf", "args": {"ctx_size": 4096}}
    mgr._current_hash = _stable_hash(preset)
    mgr._health_ok = AsyncMock(return_value=True)
    mgr._spawn = AsyncMock()
    result = await mgr.ensure_loaded(preset)
    assert result == {"loaded": True, "hash": mgr._current_hash, "swapped": False}
    mgr._spawn.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_loaded_swaps_on_hash_mismatch(tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    from app.llamacpp.manager import LlamaCppManager, _stable_hash
    mgr = LlamaCppManager()
    mgr._current_hash = "different-hash"
    # During the swap: not running, then becomes healthy after spawn.
    mgr._health_ok = AsyncMock(side_effect=[False, False, True])
    mgr._terminate = AsyncMock()
    mgr._spawn = AsyncMock()
    mgr._wait_ready = AsyncMock(return_value=True)

    preset = {"model_path": "/y.gguf", "args": {"ctx_size": 8192}}
    result = await mgr.ensure_loaded(preset)
    assert result == {"loaded": True, "hash": _stable_hash(preset), "swapped": True}
    mgr._spawn.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_loaded_timeout_raises_with_log_tail(tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    from app.llamacpp.manager import LlamaCppLoadError, LlamaCppManager
    mgr = LlamaCppManager()
    mgr._health_ok = AsyncMock(return_value=False)
    mgr._terminate = AsyncMock()
    mgr._spawn = AsyncMock()
    mgr._wait_ready = AsyncMock(return_value=False)
    mgr._log_buffer.extend([f"line-{i}" for i in range(60)])

    with pytest.raises(LlamaCppLoadError) as excinfo:
        await mgr.ensure_loaded({"model_path": "/z.gguf", "args": {}})

    msg = str(excinfo.value)
    assert "180s" in msg
    assert "line-59" in msg
    assert mgr._current_hash is None


# ---------------------------------------------------------------------------
# get_logs ring buffer
# ---------------------------------------------------------------------------

def test_get_logs_tail():
    from app.llamacpp.manager import LlamaCppManager
    mgr = LlamaCppManager()
    for i in range(700):
        mgr._log_buffer.append(f"line-{i}")
    assert len(mgr._log_buffer) == 500  # deque maxlen
    last_10 = mgr.get_logs(tail=10)
    assert len(last_10) == 10
    assert last_10[-1] == "line-699"
    all_lines = mgr.get_logs(tail=0)
    assert len(all_lines) == 500


# ---------------------------------------------------------------------------
# Router — status, config, capability gating
# ---------------------------------------------------------------------------

def test_llamacpp_status_route(client, monkeypatch):
    import app.llamacpp.router as router_mod
    mock_mgr = MagicMock()
    mock_mgr.status = AsyncMock(return_value={
        "loaded": False, "running": False, "current_preset_hash": None,
        "port": 8080, "pid": None, "uptime_seconds": None,
    })
    monkeypatch.setattr(router_mod, "get_manager", lambda: mock_mgr)

    r = client.get("/v1/llamacpp/status")
    assert r.status_code == 200
    body = r.json()
    assert body["loaded"] is False
    assert body["port"] == 8080


def test_llamacpp_config_route(client, tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", None)

    r = client.get("/v1/llamacpp/config")
    assert r.status_code == 200
    body = r.json()
    assert body["port"] == 8080
    assert "binary_path" in body


def test_llamacpp_logs_route(client, monkeypatch):
    import app.llamacpp.router as router_mod
    mock_mgr = MagicMock()
    mock_mgr.get_logs = MagicMock(return_value=["a", "b", "c"])
    monkeypatch.setattr(router_mod, "get_manager", lambda: mock_mgr)

    r = client.get("/v1/llamacpp/logs?tail=50")
    assert r.status_code == 200
    assert r.json() == {"lines": ["a", "b", "c"]}
    mock_mgr.get_logs.assert_called_once_with(tail=50)


def test_llamacpp_models_route(client, tmp_path, monkeypatch):
    import app.llamacpp.config as cfg_mod
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "a.gguf").write_bytes(b"x" * 10)
    (models_dir / "b.gguf").write_bytes(b"y" * 20)
    (models_dir / "ignored.txt").write_text("nope")

    from app.llamacpp.config import LlamaCppConfig
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(cfg_mod, "_config", LlamaCppConfig(models_dir=str(models_dir)))

    r = client.get("/v1/llamacpp/models")
    assert r.status_code == 200
    body = r.json()
    names = sorted(m["name"] for m in body["models"])
    assert names == ["a.gguf", "b.gguf"]


def test_llamacpp_routes_503_when_capability_missing(client, tmp_path, monkeypatch):
    import app.server as s
    cfg_path = tmp_path / "config" / "server.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({
        "role": "primary",
        "capabilities": ["web", "voice", "image"],
        "peers": [{"name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"]}],
    }))
    monkeypatch.setattr(s, "SERVER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(s, "_server_config", None)

    r = client.get("/v1/llamacpp/status")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["error"] == "capability_unavailable"
    assert detail["needed"] == "llm"
    assert detail["where"] == "gpu.local"


def test_llamacpp_ensure_loaded_named_preset_404_when_missing(
    client, tmp_path, monkeypatch
):
    import app.llamacpp.router as router_mod
    import app.llm_presets as presets_mod

    monkeypatch.setattr(presets_mod, "PRESETS_DIR", tmp_path / "llm_presets")
    mock_mgr = MagicMock()
    mock_mgr.ensure_loaded = AsyncMock()
    monkeypatch.setattr(router_mod, "get_manager", lambda: mock_mgr)

    r = client.post("/v1/llamacpp/ensure-loaded", json={"preset": "missing-one"})
    assert r.status_code == 404
    mock_mgr.ensure_loaded.assert_not_called()


def test_llamacpp_ensure_loaded_named_preset_resolves(client, tmp_path, monkeypatch):
    import app.llamacpp.router as router_mod
    import app.llm_presets as presets_mod
    from app.llm.models import LLMPreset

    monkeypatch.setattr(presets_mod, "PRESETS_DIR", tmp_path / "llm_presets")
    presets_mod.save_preset(
        LLMPreset(
            name="gemma-3",
            model_path="/models/gemma.gguf",
            args={"ctx_size": 4096},
            capabilities=["text"],
        )
    )

    captured: dict = {}

    async def fake_ensure(arg):
        captured["arg"] = arg
        return {"loaded": True, "hash": "h", "swapped": True}

    mock_mgr = MagicMock()
    mock_mgr.ensure_loaded = AsyncMock(side_effect=fake_ensure)
    monkeypatch.setattr(router_mod, "get_manager", lambda: mock_mgr)

    r = client.post("/v1/llamacpp/ensure-loaded", json={"preset": "gemma-3"})
    assert r.status_code == 200
    assert r.json()["swapped"] is True
    assert captured["arg"] == {"model_path": "/models/gemma.gguf", "args": {"ctx_size": 4096}}


def test_llamacpp_ensure_loaded_inline_preset(client, monkeypatch):
    import app.llamacpp.router as router_mod
    mock_mgr = MagicMock()
    mock_mgr.ensure_loaded = AsyncMock(return_value={
        "loaded": True, "hash": "abc123", "swapped": True,
    })
    monkeypatch.setattr(router_mod, "get_manager", lambda: mock_mgr)

    body = {"preset": {"model_path": "/m.gguf", "args": {"ctx_size": 4096}}}
    r = client.post("/v1/llamacpp/ensure-loaded", json=body)
    assert r.status_code == 200
    assert r.json()["swapped"] is True
    mock_mgr.ensure_loaded.assert_called_once_with(body["preset"])
