from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def patch_jobs_base(tmp_path, monkeypatch):
    """Redirect all job storage to a temp directory for each test."""
    import app.jobs as jobs_module
    monkeypatch.setattr(jobs_module, "JOBS_BASE", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def patch_omnivoice_config(tmp_path, monkeypatch):
    """Redirect OmniVoice config to tmp dir so tests don't write to the real config dir."""
    import app.omnivoice.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "config" / "omnivoice.json")
    monkeypatch.setattr(cfg, "_config", None)


@pytest.fixture(autouse=True)
def patch_voice_presets_dir(tmp_path, monkeypatch):
    """Redirect voice preset storage to a temp directory for each test."""
    import app.voice_presets as vp
    d = tmp_path / "voice_presets"
    monkeypatch.setattr(vp, "PRESETS_DIR", d)
    monkeypatch.setattr(vp, "INDEX_PATH", d / "index.json")


@pytest.fixture(autouse=True)
def patch_context_base(tmp_path, monkeypatch):
    """Redirect context file root to a temp directory for each test."""
    import app.chain.context as ctx
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(ctx, "CONTEXT_BASE", ctx_dir)
    return ctx_dir


@pytest.fixture(autouse=True)
def patch_comfyui_config(tmp_path, monkeypatch):
    """Redirect ComfyUI config to tmp dir and reset singleton."""
    import app.comfyui.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "config" / "comfyui.json")
    monkeypatch.setattr(cfg, "WORKFLOWS_DIR", tmp_path / "config" / "comfyui-workflows")
    monkeypatch.setattr(cfg, "_config", None)


@pytest.fixture(autouse=True)
def patch_execute_image_job(monkeypatch):
    """Stub out image job execution so tests don't try to reach ComfyUI."""
    import app.main as m
    mock = AsyncMock()
    monkeypatch.setattr(m, "execute_image_job", mock)
    return mock


@pytest.fixture()
def mock_execute_voice_job(monkeypatch):
    """Opt-in fixture: replaces execute_voice_job with a no-op AsyncMock.
    Request this in tests that only verify job creation, not execution."""
    import app.main as m
    mock = AsyncMock()
    monkeypatch.setattr(m, "execute_voice_job", mock)
    return mock


@pytest.fixture()
def mock_execute_chain_job(monkeypatch):
    """Opt-in fixture: replaces execute_chain_job with a no-op AsyncMock.
    Request this in tests that only verify job creation, not execution."""
    import app.main as m
    mock = AsyncMock()
    monkeypatch.setattr(m, "execute_chain_job", mock)
    return mock


@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app)
