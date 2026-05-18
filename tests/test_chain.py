from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# 1. Request validation: empty steps rejected
# ---------------------------------------------------------------------------

def test_chain_request_rejects_empty_steps(client):
    r = client.post("/v1/jobs/chain", json={
        "input": "hello",
        "llm": {"api_base": "http://fake", "model": "fake"},
        "steps": [],
    })
    assert r.status_code == 422



# ---------------------------------------------------------------------------
# 2. Template rendering
# ---------------------------------------------------------------------------

def test_render_template_all_vars():
    from app.chain.template import render_template
    result = render_template(
        "{{input}} / {{previous}} / {{context}} / {{step_index}} / {{step_name}}",
        input="INPUT",
        previous="PREV",
        context="CTX",
        step_index=3,
        step_name="My Step",
    )
    assert result == "INPUT / PREV / CTX / 3 / My Step"


def test_render_template_no_substitution_needed():
    from app.chain.template import render_template
    result = render_template(
        "plain text",
        input="x", previous="y", context="z", step_index=1, step_name="n",
    )
    assert result == "plain text"


# ---------------------------------------------------------------------------
# 3–6. Context file resolver
# ---------------------------------------------------------------------------

def test_context_resolver_loads_relative_files(tmp_path):
    import app.chain.context as ctx
    (ctx.CONTEXT_BASE / "notes.txt").write_text("hello context", encoding="utf-8")
    result = ctx.resolve_context_files(["notes.txt"])
    assert result == "hello context"


def test_context_resolver_multiple_files(tmp_path):
    import app.chain.context as ctx
    (ctx.CONTEXT_BASE / "a.txt").write_text("AAA", encoding="utf-8")
    (ctx.CONTEXT_BASE / "b.txt").write_text("BBB", encoding="utf-8")
    result = ctx.resolve_context_files(["a.txt", "b.txt"])
    assert "AAA" in result
    assert "BBB" in result


def test_context_resolver_empty_returns_empty():
    import app.chain.context as ctx
    assert ctx.resolve_context_files([]) == ""


def test_context_resolver_rejects_absolute_path():
    import app.chain.context as ctx
    with pytest.raises(ValueError, match="relative"):
        ctx.resolve_context_files(["/etc/passwd"])


def test_context_resolver_rejects_traversal():
    import app.chain.context as ctx
    with pytest.raises(ValueError, match="traverses"):
        ctx.resolve_context_files(["../secret.txt"])


def test_context_resolver_missing_file_raises():
    import app.chain.context as ctx
    with pytest.raises(FileNotFoundError, match="not found"):
        ctx.resolve_context_files(["nonexistent.txt"])


# ---------------------------------------------------------------------------
# 7–11. LLM client
# ---------------------------------------------------------------------------

async def test_llm_client_parses_valid_response():
    from app.chain.llm_client import OpenAICompatibleLLMClient
    from app.chain.models import ChainLLMConfig

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "hello from LLM"}}]
    }
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)

        cfg = ChainLLMConfig(api_base="http://fake", model="fake-model")
        result = await OpenAICompatibleLLMClient().generate("test prompt", cfg)

    assert result == "hello from LLM"


async def test_llm_client_handles_connect_error():
    from app.chain.llm_client import OpenAICompatibleLLMClient
    from app.chain.models import ChainLLMConfig

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

    with patch("httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)

        cfg = ChainLLMConfig(api_base="http://fake", model="fake")
        with pytest.raises(RuntimeError, match="not reachable"):
            await OpenAICompatibleLLMClient().generate("prompt", cfg)


async def test_llm_client_handles_timeout():
    from app.chain.llm_client import OpenAICompatibleLLMClient
    from app.chain.models import ChainLLMConfig

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)

        cfg = ChainLLMConfig(api_base="http://fake", model="fake")
        with pytest.raises(RuntimeError, match="timed out"):
            await OpenAICompatibleLLMClient().generate("prompt", cfg)


async def test_llm_client_handles_non_2xx():
    from app.chain.llm_client import OpenAICompatibleLLMClient
    from app.chain.models import ChainLLMConfig

    mock_response = MagicMock()
    mock_response.status_code = 500

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=mock_response
    )
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)

        cfg = ChainLLMConfig(api_base="http://fake", model="fake")
        with pytest.raises(RuntimeError, match="500"):
            await OpenAICompatibleLLMClient().generate("prompt", cfg)


async def test_llm_client_handles_malformed_response():
    from app.chain.llm_client import OpenAICompatibleLLMClient
    from app.chain.models import ChainLLMConfig

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"no_choices_here": []}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)

        cfg = ChainLLMConfig(api_base="http://fake", model="fake")
        with pytest.raises(RuntimeError, match="Malformed"):
            await OpenAICompatibleLLMClient().generate("prompt", cfg)


# ---------------------------------------------------------------------------
# 12. POST /v1/jobs/chain creates a job
# ---------------------------------------------------------------------------

def test_create_chain_job(client, tmp_path, mock_execute_chain_job):
    req = {
        "input": "test input",
        "llm": {"api_base": "http://debian1.local:11434/v1", "model": "gemma4"},
        "steps": [
            {"name": "outline", "type": "llm", "prompt": "outline this: {{input}}"},
        ],
    }
    r = client.post("/v1/jobs/chain", json=req)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_type"] == "chain"
    assert "job_id" in body

    job_id = body["job_id"]
    job_dirs = list(tmp_path.glob(f"*/{job_id}"))
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]

    assert (job_dir / "request.json").exists()
    assert (job_dir / "input.txt").read_text(encoding="utf-8") == "test input"
    assert (job_dir / "logs.txt").exists()
    assert (job_dir / "artifacts.json").exists()

    status = json.loads((job_dir / "status.json").read_text())
    assert status["status"] == "queued"
    assert status["job_type"] == "chain"
    assert status["step_count"] == 1

    request_data = json.loads((job_dir / "request.json").read_text())
    assert request_data["job_type"] == "chain"
    assert request_data["requested"]["input"] == "test input"


def test_create_chain_job_executor_called(client, mock_execute_chain_job):
    req = {
        "input": "run me",
        "llm": {"api_base": "http://fake", "model": "fake"},
        "steps": [{"name": "s", "type": "llm", "prompt": "p"}],
    }
    r = client.post("/v1/jobs/chain", json=req)
    assert r.status_code == 202
    mock_execute_chain_job.assert_called_once()


# ---------------------------------------------------------------------------
# 13. execute_chain_job runs two steps and writes final_output.txt
# ---------------------------------------------------------------------------

async def test_execute_chain_job_two_steps(tmp_path):
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.jobs import create_job, find_job_dir

    req = ChainJobRequest(
        input="start input",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[
            ChainStep(name="step one", prompt="First: {{input}}"),
            ChainStep(name="step two", prompt="Second: {{previous}}"),
        ],
    )

    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate = AsyncMock(side_effect=["output_one", "output_two"])
        await execute_chain_job(job_id, job_dir, req)

    assert (job_dir / "final_output.txt").read_text(encoding="utf-8") == "output_two"
    assert (job_dir / "steps" / "001_step_one" / "output.txt").read_text() == "output_one"
    assert (job_dir / "steps" / "002_step_two" / "output.txt").read_text() == "output_two"

    prompt1 = (job_dir / "steps" / "001_step_one" / "prompt.txt").read_text()
    assert "start input" in prompt1

    prompt2 = (job_dir / "steps" / "002_step_two" / "prompt.txt").read_text()
    assert "output_one" in prompt2

    status = json.loads((job_dir / "status.json").read_text())
    assert status["status"] == "done"
    assert status["progress"] == 1.0
    assert status["step_count"] == 2

    step1_status = json.loads((job_dir / "steps" / "001_step_one" / "status.json").read_text())
    assert step1_status["status"] == "done"
    assert step1_status["output_file"] == "output.txt"

    artifacts = json.loads((job_dir / "artifacts.json").read_text())
    filenames = [a["filename"] for a in artifacts]
    assert "final_output.txt" in filenames
    assert any("001_step_one" in f for f in filenames)


# ---------------------------------------------------------------------------
# 14. execute_chain_job preserves partial outputs on step 2 failure
# ---------------------------------------------------------------------------

async def test_execute_chain_job_step2_error(tmp_path):
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.jobs import create_job, find_job_dir

    req = ChainJobRequest(
        input="start",
        llm=ChainLLMConfig(api_base="http://fake", model="fake"),
        steps=[
            ChainStep(name="step one", prompt="{{input}}"),
            ChainStep(name="step two", prompt="{{previous}}"),
        ],
    )

    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate = AsyncMock(
            side_effect=["output_one", RuntimeError("step 2 failed")]
        )
        await execute_chain_job(job_id, job_dir, req)

    # Step 1 output preserved
    assert (job_dir / "steps" / "001_step_one" / "output.txt").read_text() == "output_one"
    step1_status = json.loads(
        (job_dir / "steps" / "001_step_one" / "status.json").read_text()
    )
    assert step1_status["status"] == "done"

    # Step 2 in error
    step2_status = json.loads(
        (job_dir / "steps" / "002_step_two" / "status.json").read_text()
    )
    assert step2_status["status"] == "error"
    assert "step 2 failed" in step2_status["error"]

    # Parent status is error
    parent_status = json.loads((job_dir / "status.json").read_text())
    assert parent_status["status"] == "error"
    assert "step 2 failed" in parent_status["error"]

    # final_output.txt not written
    assert not (job_dir / "final_output.txt").exists()

    # Error logged
    logs = (job_dir / "logs.txt").read_text()
    assert "step 2 failed" in logs


# ---------------------------------------------------------------------------
# 15. UI contains "Chain Jobs"
# ---------------------------------------------------------------------------

def test_ui_contains_chain_page():
    ui_path = Path(__file__).parent.parent / "static" / "chain" / "index.html"
    content = ui_path.read_text(encoding="utf-8")
    assert "chain.js" in content


# ---------------------------------------------------------------------------
# GET /v1/jobs/{job_id}/steps
# ---------------------------------------------------------------------------

def test_get_chain_steps_no_steps_yet(client, mock_execute_chain_job):
    req = {
        "input": "hello",
        "llm": {"api_base": "http://fake", "model": "fake"},
        "steps": [{"name": "s", "type": "llm", "prompt": "p"}],
    }
    r = client.post("/v1/jobs/chain", json=req)
    job_id = r.json()["job_id"]

    r2 = client.get(f"/v1/jobs/{job_id}/steps")
    assert r2.status_code == 200
    assert r2.json()["steps"] == []


def test_get_chain_steps_not_found(client):
    r = client.get("/v1/jobs/00000000-0000-0000-0000-000000000000/steps")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Existing file endpoint still works with :path route change
# ---------------------------------------------------------------------------

def test_get_job_file_status_still_works(client):
    r = client.post("/v1/jobs/image", json={"workflow": "test_wf", "prompt": "test"})
    job_id = r.json()["job_id"]
    r2 = client.get(f"/v1/jobs/{job_id}/files/status.json")
    assert r2.status_code == 200


# ---------------------------------------------------------------------------
# Per-step LLM preset selector + ensure-loaded wiring
# ---------------------------------------------------------------------------


def _save_llm_model_preset(name, capabilities=("text",), model_path="/tmp/fake.gguf"):
    """Helper: write a minimal LLMPreset JSON into the test preset dir."""
    from app import llm_presets
    from app.llm.models import LLMPreset
    preset = LLMPreset(name=name, model_path=model_path,
                       args={"ctx_size": 4096}, capabilities=list(capabilities))
    llm_presets.save_preset(preset)


def test_chain_step_accepts_preset_and_requires():
    from app.chain.models import ChainStep
    s = ChainStep(name="visual", prompt="describe", preset="vision-small",
                  requires=["vision", "text"])
    # v2 hoists v1-style flat fields onto a single alternative.
    assert s.alternatives[0].preset == "vision-small"
    assert s.alternatives[0].requires == ["vision", "text"]


def test_save_sequence_rejects_when_preset_lacks_capabilities(tmp_path, monkeypatch):
    from app.chain import sequences
    seqdir = tmp_path / "seq"
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", seqdir)
    monkeypatch.setattr(sequences, "INDEX_PATH", seqdir / "index.json")
    _save_llm_model_preset("text-only", capabilities=["text"])
    with pytest.raises(ValueError, match="missing required capabilities"):
        sequences.save_sequence("bad-seq", [
            {"name": "needs vision", "type": "llm",
             "preset": "text-only", "requires": ["vision"]},
        ])


def test_save_sequence_accepts_when_preset_has_all_capabilities(tmp_path, monkeypatch):
    from app.chain import sequences
    seqdir = tmp_path / "seq"
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", seqdir)
    monkeypatch.setattr(sequences, "INDEX_PATH", seqdir / "index.json")
    _save_llm_model_preset("multimodal", capabilities=["text", "vision"])
    result = sequences.save_sequence("ok-seq", [
        {"name": "describe image", "type": "llm",
         "preset": "multimodal", "requires": ["vision"]},
    ])
    assert result["name"] == "ok-seq"


def test_save_sequence_rejects_unknown_preset(tmp_path, monkeypatch):
    from app.chain import sequences
    seqdir = tmp_path / "seq"
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", seqdir)
    monkeypatch.setattr(sequences, "INDEX_PATH", seqdir / "index.json")
    with pytest.raises(ValueError, match="unknown LLM preset"):
        sequences.save_sequence("ghost-seq", [
            {"name": "ghost", "type": "llm",
             "preset": "does-not-exist", "requires": ["text"]},
        ])


def test_save_sequence_rejects_requires_without_any_preset(tmp_path, monkeypatch):
    from app.chain import sequences
    from app.llamacpp import config as llcfg
    seqdir = tmp_path / "seq"
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", seqdir)
    monkeypatch.setattr(sequences, "INDEX_PATH", seqdir / "index.json")
    # Force a clean llamacpp config with no default_preset.
    monkeypatch.setattr(llcfg, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(llcfg, "_config", None)
    with pytest.raises(ValueError, match="no preset is selected"):
        sequences.save_sequence("orphan-seq", [
            {"name": "needs text", "type": "llm", "requires": ["text"]},
        ])


async def test_executor_calls_ensure_loaded_with_step_preset(tmp_path, monkeypatch):
    """A step with `preset` set must POST that name to /v1/llamacpp/ensure-loaded
    before the chat-completion call, and override the api_base + model used."""
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.jobs import create_job, find_job_dir
    from app.llamacpp import config as llcfg
    monkeypatch.setattr(llcfg, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(llcfg, "_config", None)
    # config defaults to port 8080; local has 'llm' capability via patch_server_config

    _save_llm_model_preset("alpha", capabilities=["text"])

    req = ChainJobRequest(
        input="hi",
        llm=ChainLLMConfig(api_base="http://will-be-overridden", model="placeholder"),
        steps=[ChainStep(name="one", prompt="{{input}}", preset="alpha")],
    )
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    posted: dict = {}

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"loaded": True, "hash": "abc", "swapped": True}

    async def _fake_post(self, url, json=None, **kw):
        posted["url"] = url
        posted["json"] = json
        return _Resp()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate = AsyncMock(return_value="model-said-hi")
        await execute_chain_job(job_id, job_dir, req)

    # ensure-loaded hits the FastAPI control plane (typically :8090 locally).
    assert posted["url"] == "http://127.0.0.1:8090/v1/llamacpp/ensure-loaded"
    assert posted["json"] == {"preset": "alpha"}

    # generate was called with the overridden llm config (api_base + model).
    # The chat-completion api_base points at the llama-server data plane (:8080).
    call_args = instance.generate.await_args
    used_llm = call_args.args[1]
    assert used_llm.api_base == "http://127.0.0.1:8080/v1"
    assert used_llm.model == "alpha"

    logs = (job_dir / "logs.txt").read_text(encoding="utf-8")
    assert "LLM swap" in logs and "alpha" in logs


async def test_executor_falls_back_to_default_preset(tmp_path, monkeypatch):
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.jobs import create_job, find_job_dir
    from app.llamacpp import config as llcfg
    cfg_path = tmp_path / "llamacpp.json"
    cfg_path.write_text(
        '{"binary_path":"/x","port":8080,"default_preset":"beta","models_dir":"/m"}'
    )
    monkeypatch.setattr(llcfg, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(llcfg, "_config", None)

    _save_llm_model_preset("beta", capabilities=["text"])

    req = ChainJobRequest(
        input="hi",
        llm=ChainLLMConfig(api_base="http://orig", model="orig"),
        steps=[ChainStep(name="one", prompt="{{input}}")],  # no preset
    )
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    posted: dict = {}

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"loaded": True, "hash": "h", "swapped": False}

    async def _fake_post(self, url, json=None, **kw):
        posted["json"] = json
        return _Resp()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate = AsyncMock(return_value="ok")
        await execute_chain_job(job_id, job_dir, req)

    assert posted["json"] == {"preset": "beta"}


async def test_executor_step_errors_on_ensure_loaded_failure(tmp_path, monkeypatch):
    from app.chain.executor import execute_chain_job
    from app.chain.models import ChainJobRequest, ChainLLMConfig, ChainStep
    from app.jobs import create_job, find_job_dir
    from app.llamacpp import config as llcfg
    monkeypatch.setattr(llcfg, "CONFIG_PATH", tmp_path / "llamacpp.json")
    monkeypatch.setattr(llcfg, "_config", None)

    _save_llm_model_preset("gamma", capabilities=["text"])

    req = ChainJobRequest(
        input="hi",
        llm=ChainLLMConfig(api_base="http://orig", model="orig"),
        steps=[ChainStep(name="one", prompt="{{input}}", preset="gamma")],
    )
    data = create_job("chain", req.model_dump(), req.input)
    job_id = data["job_id"]
    job_dir = find_job_dir(job_id)

    class _Resp:
        status_code = 503
        text = "model fail"
        def json(self):  # not used on error path
            return {}

    async def _fake_post(self, url, json=None, **kw):
        return _Resp()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

    with patch("app.chain.executor.OpenAICompatibleLLMClient") as MockClient:
        instance = MockClient.return_value
        instance.generate = AsyncMock(return_value="should-not-run")
        await execute_chain_job(job_id, job_dir, req)

    parent_status = json.loads((job_dir / "status.json").read_text())
    assert parent_status["status"] == "error"
    assert "ensure-loaded" in parent_status["error"]
    # generate must not have been called once ensure-loaded failed
    instance.generate.assert_not_awaited()
