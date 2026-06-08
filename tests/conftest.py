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
def reset_job_queue_singleton():
    """Drop the JobQueue singleton between tests so each test's event loop
    gets a fresh asyncio.Queue. Without this, the cached queue would be bound
    to the previous test's (now closed) event loop."""
    import app.job_queue as jq
    jq.reset_job_queue()
    yield
    jq.reset_job_queue()


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
def patch_llm_presets_dir(tmp_path, monkeypatch):
    """Redirect LLM preset storage to a temp directory for each test."""
    import app.llm_presets as lp
    monkeypatch.setattr(lp, "PRESETS_DIR", tmp_path / "llm_presets")


@pytest.fixture(autouse=True)
def patch_context_base(tmp_path, monkeypatch):
    """Redirect context file root to a temp directory for each test."""
    import app.chain.context as ctx
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(ctx, "CONTEXT_BASE", ctx_dir)
    return ctx_dir


@pytest.fixture(autouse=True)
def patch_prompt_pal_dir(tmp_path, monkeypatch):
    """Redirect Prompt Pal storage to a temp directory for each test.

    With an empty store, `service.get_text` falls back to the in-code registered
    defaults — which keeps Blaboratory's `get_prompt` back-compat tests green.
    """
    import app.prompt_pal.store as pp
    monkeypatch.setattr(pp, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")


@pytest.fixture(autouse=True)
def patch_hoodat_dirs(tmp_path, monkeypatch):
    """Redirect Hoodat character + avatar storage to a temp directory."""
    import app.apps.hoodat.characters_store as cs
    import app.apps.hoodat.avatars as av
    monkeypatch.setattr(cs, "CHARACTERS_DIR", tmp_path / "hoodat" / "characters")
    monkeypatch.setattr(av, "AVATARS_DIR", tmp_path / "hoodat" / "avatars")


@pytest.fixture(autouse=True)
def patch_memory_base(tmp_path, monkeypatch):
    """Redirect memory storage to a temp dir; reset the config + service singletons.

    Keeps memory tests isolated and ensures the rest of the suite never writes real
    memory files. Defaults to the plain backend (no external services)."""
    import app.memory.config as mcfg
    import app.memory.service as msvc
    monkeypatch.setattr(mcfg, "BASE_DIR", tmp_path / "memory")
    mcfg.reset_config()
    msvc.reset_service()
    yield
    mcfg.reset_config()
    msvc.reset_service()


@pytest.fixture(autouse=True)
def patch_server_config(tmp_path, monkeypatch):
    """Redirect server config to tmp dir and reset cache.

    Tests get the default ServerConfig (all capabilities enabled) unless they
    write their own config/server.json into tmp_path and call reset_server_config().
    """
    import app.server as s
    monkeypatch.setattr(s, "SERVER_CONFIG_PATH", tmp_path / "config" / "server.json")
    monkeypatch.setattr(s, "_server_config", None)


@pytest.fixture(autouse=True)
def patch_textdiff_dir(tmp_path, monkeypatch):
    """Redirect textdiff proposal storage to a temp directory for each test."""
    import app.textdiff.store as td
    monkeypatch.setattr(td, "TEXTDIFF_DIR", tmp_path / "textdiff")


@pytest.fixture(autouse=True)
def patch_comfyui_config(tmp_path, monkeypatch):
    """Redirect ComfyUI config to tmp dir and reset singleton."""
    import app.comfyui.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "config" / "comfyui.json")
    monkeypatch.setattr(cfg, "WORKFLOWS_DIR", tmp_path / "config" / "comfyui-workflows")
    monkeypatch.setattr(cfg, "_config", None)


@pytest.fixture(autouse=True)
def patch_llamacpp_config(tmp_path, monkeypatch):
    """Redirect llamacpp config to tmp dir and reset singleton.

    Without this, chain tests that exercise the executor would pick up the
    host's `default_preset` from config/llamacpp.json and route through
    ensure_loaded_for_step → real HTTP. Defaulting to an empty tmp config
    means `default_preset` is None and the swap is skipped automatically.
    """
    import app.llamacpp.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "config" / "llamacpp.json")
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
