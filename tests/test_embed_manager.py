"""D1.2a — app-managed embed llama-server + control routes.

Subprocess + httpx are mocked exactly like the existing llama.cpp manager tests
(``test_llamacpp.py``): we never spawn a real server, we assert on the argv and
the lifecycle transitions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _cfg(tmp_path, monkeypatch, **overrides):
    import app.llamacpp.config as cfg_mod
    from app.llamacpp.config import LlamaCppConfig

    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "llamacpp.json")
    cfg = LlamaCppConfig(**overrides)
    monkeypatch.setattr(cfg_mod, "_config", cfg)
    return cfg


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

def test_embed_config_defaults(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch)
    assert cfg.embed_port == 8081
    assert cfg.embed_pooling == "cls"
    assert cfg.embed_model_path is None


# ---------------------------------------------------------------------------
# argv
# ---------------------------------------------------------------------------

def test_build_argv_fixed_embed_preset(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, embed_model_path="/models/bge.gguf", embed_port=8081)
    from app.llamacpp.embed_manager import LlamaCppEmbedManager

    argv = LlamaCppEmbedManager()._build_argv()
    assert argv[0].endswith("llama-server")
    assert "--model" in argv and "/models/bge.gguf" in argv
    assert "--embeddings" in argv
    assert argv[argv.index("--pooling") + 1] == "cls"
    assert argv[argv.index("--port") + 1] == "8081"
    assert argv[argv.index("--ctx-size") + 1] == "512"
    assert "-ngl" in argv and argv[argv.index("-ngl") + 1] == "99"


def test_build_argv_raises_without_model(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, embed_model_path=None)
    from app.llamacpp.embed_manager import LlamaCppEmbedManager
    from app.llamacpp.manager import LlamaCppLoadError

    with pytest.raises(LlamaCppLoadError):
        LlamaCppEmbedManager()._build_argv()


# ---------------------------------------------------------------------------
# start / adopt / readiness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_spawns_embed_argv(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, embed_model_path="/models/bge.gguf", embed_port=8081)
    from app.llamacpp.embed_manager import LlamaCppEmbedManager

    mgr = LlamaCppEmbedManager()
    # not healthy initially → spawn path; healthy afterward for _status
    mgr._health_ok = AsyncMock(side_effect=[False, True])
    mgr._spawn = AsyncMock()
    mgr._wait_ready = AsyncMock(return_value=True)

    status = await mgr.start()
    mgr._spawn.assert_called_once()
    argv = mgr._spawn.call_args.args[0]
    assert "--embeddings" in argv and argv[argv.index("--port") + 1] == "8081"
    assert status["running"] is True
    assert status["port"] == 8081


@pytest.mark.asyncio
async def test_adopt_picks_up_running_server(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, embed_model_path="/models/bge.gguf")
    from app.llamacpp.embed_manager import LlamaCppEmbedManager

    mgr = LlamaCppEmbedManager()
    mgr._health_ok = AsyncMock(return_value=True)
    mgr._find_pid_on_port = MagicMock(return_value=4242)

    assert await mgr.adopt() is True
    assert mgr._our_pid() == 4242


@pytest.mark.asyncio
async def test_start_readiness_timeout_raises_and_clears(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch, embed_model_path="/models/bge.gguf")
    from app.llamacpp.embed_manager import LlamaCppEmbedManager
    from app.llamacpp.manager import LlamaCppLoadError

    mgr = LlamaCppEmbedManager()
    mgr._health_ok = AsyncMock(return_value=False)
    mgr._spawn = AsyncMock()
    mgr._wait_ready = AsyncMock(return_value=False)
    mgr._terminate = AsyncMock()
    mgr._log_buffer.extend([f"line-{i}" for i in range(60)])

    with pytest.raises(LlamaCppLoadError) as excinfo:
        await mgr.start()
    msg = str(excinfo.value)
    assert "180s" in msg
    assert "line-59" in msg
    mgr._terminate.assert_awaited_once()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def test_embed_status_route(client, monkeypatch):
    import app.llamacpp.embed_router as r
    mock = MagicMock()
    mock.status = AsyncMock(
        return_value={"running": False, "port": 8081, "model_path": None, "pid": None, "uptime_seconds": None}
    )
    monkeypatch.setattr(r, "get_embed_manager", lambda: mock)

    resp = client.get("/v1/llamacpp-embed/status")
    assert resp.status_code == 200
    assert resp.json()["port"] == 8081


def test_embed_logs_route(client, monkeypatch):
    import app.llamacpp.embed_router as r
    mock = MagicMock()
    mock.get_logs = MagicMock(return_value=["a", "b"])
    monkeypatch.setattr(r, "get_embed_manager", lambda: mock)

    resp = client.get("/v1/llamacpp-embed/logs?tail=10")
    assert resp.status_code == 200
    assert resp.json() == {"lines": ["a", "b"]}
    mock.get_logs.assert_called_once_with(tail=10)


def test_embed_start_503_on_load_error(client, monkeypatch):
    import app.llamacpp.embed_router as r
    from app.llamacpp.manager import LlamaCppLoadError

    mock = MagicMock()
    mock.start = AsyncMock(side_effect=LlamaCppLoadError("no model"))
    monkeypatch.setattr(r, "get_embed_manager", lambda: mock)

    resp = client.post("/v1/llamacpp-embed/start")
    assert resp.status_code == 503
    assert "no model" in resp.json()["detail"]
