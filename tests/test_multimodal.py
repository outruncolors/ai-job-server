from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.chain.llm_swap import LLMSwapError
from app.chain.models import ChainLLMConfig
from app.multimodal import service, swap


# ── transcode_to_wav ────────────────────────────────────────────────────────


class _FakeProc:
    def __init__(self, out=b"WAVDATA", err=b"", returncode=0):
        self._out = out
        self._err = err
        self.returncode = returncode

    async def communicate(self, input=None):  # noqa: A002 - mirror asyncio API
        return self._out, self._err


async def test_transcode_to_wav_ok(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return _FakeProc(out=b"RIFF....WAVE")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    out = await service.transcode_to_wav(b"some-webm-bytes")
    assert out == b"RIFF....WAVE"


async def test_transcode_to_wav_empty_input():
    with pytest.raises(service.TranscodeError):
        await service.transcode_to_wav(b"")


async def test_transcode_to_wav_ffmpeg_missing(monkeypatch):
    async def fake_exec(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(service.TranscodeError, match="ffmpeg not found"):
        await service.transcode_to_wav(b"data")


async def test_transcode_to_wav_nonzero_returncode(monkeypatch):
    async def fake_exec(*args, **kwargs):
        return _FakeProc(out=b"", err=b"bad audio", returncode=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(service.TranscodeError, match="bad audio"):
        await service.transcode_to_wav(b"data")


# ── resolve_multimodal_preset ───────────────────────────────────────────────


def _set_multimodal_preset(monkeypatch, value):
    import app.llamacpp.config as cfg
    monkeypatch.setattr(cfg, "_config", cfg.LlamaCppConfig(multimodal_preset=value))


def test_resolve_multimodal_preset_set(monkeypatch):
    _set_multimodal_preset(monkeypatch, "gemma-4-e4b-mm")
    assert swap.resolve_multimodal_preset() == "gemma-4-e4b-mm"


def test_resolve_multimodal_preset_unset(monkeypatch):
    _set_multimodal_preset(monkeypatch, None)
    with pytest.raises(LLMSwapError, match="multimodal_preset"):
        swap.resolve_multimodal_preset()


# ── run_vision / run_stt message shapes ─────────────────────────────────────


async def test_run_vision_builds_image_message(monkeypatch):
    cfg = ChainLLMConfig(api_base="http://x/v1", model="gemma-4-e4b-mm")
    monkeypatch.setattr(service, "ensure_multimodal_loaded", AsyncMock(return_value=cfg))
    captured = {}

    async def fake_chat(self, messages, llm_config, tools=None):
        captured["messages"] = messages
        captured["cfg"] = llm_config
        return {"message": {"content": "a red cat"}}

    monkeypatch.setattr(service.OpenAICompatibleLLMClient, "chat", fake_chat)

    out = await service.run_vision(b"\x89PNG...", "image/png", "What is this?")
    assert out == "a red cat"
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "What is this?"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert captured["cfg"] is cfg


async def test_run_vision_default_prompt(monkeypatch):
    cfg = ChainLLMConfig(api_base="http://x/v1", model="m")
    monkeypatch.setattr(service, "ensure_multimodal_loaded", AsyncMock(return_value=cfg))

    async def fake_chat(self, messages, llm_config, tools=None):
        return {"message": {"content": "desc"}}

    captured = {}

    async def capture_chat(self, messages, llm_config, tools=None):
        captured["messages"] = messages
        return {"message": {"content": "desc"}}

    monkeypatch.setattr(service.OpenAICompatibleLLMClient, "chat", capture_chat)
    await service.run_vision(b"img", "image/jpeg", "")
    assert captured["messages"][0]["content"][0]["text"] == service.DEFAULT_VISION_PROMPT


async def test_run_stt_builds_audio_message(monkeypatch):
    cfg = ChainLLMConfig(api_base="http://x/v1", model="m")
    monkeypatch.setattr(service, "ensure_multimodal_loaded", AsyncMock(return_value=cfg))
    captured = {}

    async def fake_chat(self, messages, llm_config, tools=None):
        captured["messages"] = messages
        return {"message": {"content": "hello world"}}

    monkeypatch.setattr(service.OpenAICompatibleLLMClient, "chat", fake_chat)

    out = await service.run_stt(b"RIFFWAVE", "")
    assert out == "hello world"
    content = captured["messages"][0]["content"]
    assert content[1]["type"] == "input_audio"
    assert content[1]["input_audio"]["format"] == "wav"
    assert content[1]["input_audio"]["data"]  # base64 present


async def test_run_vision_empty_content_raises(monkeypatch):
    cfg = ChainLLMConfig(api_base="http://x/v1", model="m")
    monkeypatch.setattr(service, "ensure_multimodal_loaded", AsyncMock(return_value=cfg))

    async def fake_chat(self, messages, llm_config, tools=None):
        return {"message": {"content": ""}}

    monkeypatch.setattr(service.OpenAICompatibleLLMClient, "chat", fake_chat)
    with pytest.raises(RuntimeError, match="empty content"):
        await service.run_vision(b"img", "image/png", "x")


# ── job routes (POST /v1/jobs/{vision,stt}) ─────────────────────────────────
#
# Vision/STT now run through the JobQueue like image/voice. The route saves the
# upload and enqueues a runner; we patch the runner to a no-op AsyncMock so the
# route test stays offline and just asserts the job-creation contract.


def test_vision_job_route_creates_job(client, monkeypatch, patch_jobs_base):
    import app.main as m
    from app.jobs import find_job_dir
    monkeypatch.setattr(m, "execute_vision_job", AsyncMock())
    resp = client.post(
        "/v1/jobs/vision",
        files={"file": ("cat.png", b"\x89PNG-bytes", "image/png")},
        data={"prompt": "what is this?"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_type"] == "vision"
    job_dir = find_job_dir(body["job_id"])
    assert (job_dir / "input.png").read_bytes() == b"\x89PNG-bytes"
    req = json.loads((job_dir / "request.json").read_text())["requested"]
    assert req == {"prompt": "what is this?", "mime": "image/png", "input_filename": "input.png"}


def test_vision_job_route_rejects_non_image(client):
    resp = client.post(
        "/v1/jobs/vision",
        files={"file": ("note.txt", b"hi", "text/plain")},
    )
    assert resp.status_code == 415


def test_vision_job_route_rejects_empty(client, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "execute_vision_job", AsyncMock())
    resp = client.post(
        "/v1/jobs/vision",
        files={"file": ("cat.png", b"", "image/png")},
    )
    assert resp.status_code == 422


def test_stt_job_route_creates_job(client, monkeypatch, patch_jobs_base):
    import app.main as m
    from app.jobs import find_job_dir
    monkeypatch.setattr(m, "execute_stt_job", AsyncMock())
    resp = client.post(
        "/v1/jobs/stt",
        files={"file": ("recording.webm", b"webmbytes", "audio/webm")},
        data={"prompt": ""},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_type"] == "stt"
    job_dir = find_job_dir(body["job_id"])
    assert (job_dir / "input.webm").read_bytes() == b"webmbytes"
    req = json.loads((job_dir / "request.json").read_text())["requested"]
    assert req["content_type"] == "audio/webm"
    assert req["input_filename"] == "input.webm"


# ── runners (execute_vision_job / execute_stt_job) ──────────────────────────


def _make_job(jobs_base, job_type, requested, input_filename, input_bytes):
    """Create a job on disk (per create_job) and drop the input file in place."""
    from app.jobs import create_job, find_job_dir
    data = create_job(job_type, requested, input_text=requested.get("prompt", ""))
    job_dir = find_job_dir(data["job_id"])
    (job_dir / input_filename).write_bytes(input_bytes)
    return data["job_id"], job_dir


async def test_execute_vision_job_writes_output(patch_jobs_base, monkeypatch):
    from app.models import VisionJobRequest
    from app.multimodal import runner as mm
    monkeypatch.setattr(mm, "run_vision", AsyncMock(return_value="a sleeping cat"))

    requested = {"prompt": "describe", "mime": "image/png", "input_filename": "input.png"}
    job_id, job_dir = _make_job(patch_jobs_base, "vision", requested, "input.png", b"\x89PNG")
    await mm.execute_vision_job(job_id, job_dir, VisionJobRequest(**requested))

    assert (job_dir / "output.txt").read_text() == "a sleeping cat"
    status = json.loads((job_dir / "status.json").read_text())
    assert status["status"] == "done"
    artifacts = json.loads((job_dir / "artifacts.json").read_text())
    assert any(a["filename"] == "output.txt" for a in artifacts)
    # run_vision got the saved image bytes + mime.
    assert mm.run_vision.await_args.args[:2] == (b"\x89PNG", "image/png")


async def test_execute_vision_job_error_marks_status(patch_jobs_base, monkeypatch):
    from app.models import VisionJobRequest
    from app.multimodal import runner as mm
    monkeypatch.setattr(mm, "run_vision", AsyncMock(side_effect=LLMSwapError("no llm node")))

    requested = {"prompt": "", "mime": "image/png", "input_filename": "input.png"}
    job_id, job_dir = _make_job(patch_jobs_base, "vision", requested, "input.png", b"\x89PNG")
    await mm.execute_vision_job(job_id, job_dir, VisionJobRequest(**requested))

    status = json.loads((job_dir / "status.json").read_text())
    assert status["status"] == "error"
    assert "no llm node" in status["error"]
    assert "[error]" in (job_dir / "logs.txt").read_text()
    assert not (job_dir / "output.txt").exists()


async def test_execute_stt_job_transcodes_and_writes(patch_jobs_base, monkeypatch):
    from app.models import SttJobRequest
    from app.multimodal import runner as mm
    monkeypatch.setattr(mm, "transcode_to_wav", AsyncMock(return_value=b"RIFFWAVE"))
    monkeypatch.setattr(mm, "run_stt", AsyncMock(return_value="hello world"))

    requested = {"prompt": "", "content_type": "audio/webm", "input_filename": "input.webm"}
    job_id, job_dir = _make_job(patch_jobs_base, "stt", requested, "input.webm", b"webmbytes")
    await mm.execute_stt_job(job_id, job_dir, SttJobRequest(**requested))

    assert (job_dir / "output.txt").read_text() == "hello world"
    assert json.loads((job_dir / "status.json").read_text())["status"] == "done"
    # transcode got the raw upload; run_stt got the transcoded wav.
    assert mm.transcode_to_wav.await_args.args[0] == b"webmbytes"
    assert mm.run_stt.await_args.args[0] == b"RIFFWAVE"


# ── recovery rebuilds runners for vision/stt ────────────────────────────────


def test_recovery_builds_vision_runner():
    from app.main import _build_recovery_runner
    entry = {
        "job_type": "vision",
        "job_id": "abc",
        "job_dir": object(),
        "request": {"requested": {"prompt": "x", "mime": "image/png", "input_filename": "input.png"}},
    }
    assert _build_recovery_runner(entry) is not None


def test_recovery_builds_stt_runner():
    from app.main import _build_recovery_runner
    entry = {
        "job_type": "stt",
        "job_id": "abc",
        "job_dir": object(),
        "request": {"requested": {"prompt": "", "content_type": "audio/webm", "input_filename": "input.webm"}},
    }
    assert _build_recovery_runner(entry) is not None
