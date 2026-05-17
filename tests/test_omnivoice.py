from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Config fixtures (local to this file)
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_config_path(tmp_path, monkeypatch):
    """Patch CONFIG_PATH to a fresh tmp path and reset the cache."""
    import app.omnivoice.config as cfg
    config_path = tmp_path / "config" / "omnivoice.json"
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_path)
    monkeypatch.setattr(cfg, "_config", None)
    return config_path


# ---------------------------------------------------------------------------
# 1. Default config creation
# ---------------------------------------------------------------------------

def test_default_config_created(tmp_config_path):
    from app.omnivoice.config import load_config
    config = load_config()
    assert config.voice == "default"
    assert config.speed == 1.0
    assert config.model == "k2-fsa/OmniVoice"
    assert tmp_config_path.exists()
    saved = json.loads(tmp_config_path.read_text())
    assert saved["model"] == "k2-fsa/OmniVoice"


# ---------------------------------------------------------------------------
# 2. GET /v1/omnivoice/status returns the current shape
# ---------------------------------------------------------------------------

def test_status_endpoint_shape(client, tmp_config_path):
    r = client.get("/v1/omnivoice/status")
    assert r.status_code == 200
    body = r.json()
    assert "ephemeral_available" in body
    assert "active_voice_jobs" in body
    assert "infer_base_command" in body


# ---------------------------------------------------------------------------
# 3. PUT /v1/omnivoice/config rejects speed out of range
# ---------------------------------------------------------------------------

def test_put_config_speed_out_of_range(client, tmp_config_path):
    r = client.put("/v1/omnivoice/config", json={"speed": 99.0})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 4. OmniVoiceEphemeralRunner.build_command() produces correct arg list
# ---------------------------------------------------------------------------

def test_ephemeral_runner_build_command():
    from app.omnivoice.config import OmniVoiceConfig
    from app.omnivoice.runner import OmniVoiceEphemeralRunner

    config = OmniVoiceConfig(model="k2-fsa/OmniVoice", language="English")
    runner = OmniVoiceEphemeralRunner(config)
    cmd = runner.build_command("hello world", Path("/tmp/out.wav"))

    assert cmd[0] == "omnivoice-infer"
    assert "--model" in cmd
    assert "k2-fsa/OmniVoice" in cmd
    assert "--text" in cmd
    assert "hello world" in cmd
    assert "--output" in cmd
    assert "/tmp/out.wav" in cmd
    assert "--language" in cmd
    assert "English" in cmd


def test_ephemeral_runner_build_command_custom_base():
    from app.omnivoice.config import OmniVoiceConfig
    from app.omnivoice.runner import OmniVoiceEphemeralRunner

    config = OmniVoiceConfig(infer_base_command=["python", "-m", "omnivoice"])
    runner = OmniVoiceEphemeralRunner(config)
    cmd = runner.build_command("hi", Path("/out.wav"))

    assert cmd[:3] == ["python", "-m", "omnivoice"]
    assert "--text" in cmd


# ---------------------------------------------------------------------------
# 8. Ephemeral runner raises RuntimeError for missing binary
# ---------------------------------------------------------------------------

async def test_ephemeral_runner_missing_binary(tmp_path):
    from app.omnivoice.config import OmniVoiceConfig
    from app.omnivoice.runner import OmniVoiceEphemeralRunner

    config = OmniVoiceConfig()
    runner = OmniVoiceEphemeralRunner(config)

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("no such file"),
    ):
        with pytest.raises(RuntimeError, match="not installed"):
            await runner.run("hello", tmp_path / "out.wav", tmp_path)


# ---------------------------------------------------------------------------
# 9. POST /v1/jobs/voice stores requested and effective settings
# ---------------------------------------------------------------------------

async def test_voice_job_stores_requested_and_effective(client, tmp_path):
    """Real execute_voice_job runs; OmniVoice not installed, so it fails
    gracefully, but effective settings must be written before synthesis."""
    r = client.post(
        "/v1/jobs/voice",
        json={"text": "test synthesis", "voice": "test-voice", "speed": 1.5},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    job_dirs = list(tmp_path.glob(f"*/{job_id}"))
    assert len(job_dirs) == 1
    req_data = json.loads((job_dirs[0] / "request.json").read_text())

    assert req_data["job_type"] == "voice"
    assert "requested" in req_data
    assert req_data["requested"]["text"] == "test synthesis"
    assert req_data["requested"]["voice"] == "test-voice"
    assert "effective" in req_data
    assert "model" in req_data["effective"]
    assert req_data["effective"]["voice"] == "test-voice"
    assert req_data["effective"]["speed"] == 1.5


# ---------------------------------------------------------------------------
# 10. POST /v1/jobs/voice triggers background task (mock path)
# ---------------------------------------------------------------------------

def test_post_voice_job_triggers_background_task(client, mock_execute_voice_job):
    r = client.post("/v1/jobs/voice", json={"text": "synthesize this"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_type"] == "voice"

    mock_execute_voice_job.assert_called_once()
    call_args = mock_execute_voice_job.call_args
    assert call_args.args[0] == body["job_id"]


# ---------------------------------------------------------------------------
# 11. GET / loads (UI route)
# ---------------------------------------------------------------------------

def test_ui_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"AI Job Server" in r.content
