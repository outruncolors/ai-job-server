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


def test_chain_request_rejects_empty_input(client):
    r = client.post("/v1/jobs/chain", json={
        "input": "",
        "llm": {"api_base": "http://fake", "model": "fake"},
        "steps": [{"name": "s", "type": "llm", "prompt": "p"}],
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

def test_ui_contains_chain_jobs():
    ui_path = Path(__file__).parent.parent / "static" / "index.html"
    content = ui_path.read_text(encoding="utf-8")
    assert "Chain Jobs" in content


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
    r = client.post("/v1/jobs/image", json={"prompt": "test"})
    job_id = r.json()["job_id"]
    r2 = client.get(f"/v1/jobs/{job_id}/files/status.json")
    assert r2.status_code == 200
