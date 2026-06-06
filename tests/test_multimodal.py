from __future__ import annotations

import asyncio
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


# ── routes ──────────────────────────────────────────────────────────────────


def test_vision_route_ok(client, monkeypatch):
    import app.multimodal.router as r
    monkeypatch.setattr(r, "run_vision", AsyncMock(return_value="a dog"))
    resp = client.post(
        "/v1/multimodal/vision",
        files={"file": ("cat.png", b"\x89PNG", "image/png")},
        data={"prompt": "what?"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"text": "a dog"}


def test_vision_route_rejects_non_image(client):
    resp = client.post(
        "/v1/multimodal/vision",
        files={"file": ("note.txt", b"hi", "text/plain")},
    )
    assert resp.status_code == 415


def test_vision_route_swap_error_503(client, monkeypatch):
    import app.multimodal.router as r
    monkeypatch.setattr(r, "run_vision", AsyncMock(side_effect=LLMSwapError("no llm node")))
    resp = client.post(
        "/v1/multimodal/vision",
        files={"file": ("cat.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 503
    assert "no llm node" in resp.json()["detail"]


def test_stt_route_ok(client, monkeypatch):
    import app.multimodal.router as r
    monkeypatch.setattr(r, "transcode_to_wav", AsyncMock(return_value=b"RIFFWAVE"))
    monkeypatch.setattr(r, "run_stt", AsyncMock(return_value="transcript here"))
    resp = client.post(
        "/v1/multimodal/stt",
        files={"file": ("rec.webm", b"webmbytes", "audio/webm")},
        data={"prompt": ""},
    )
    assert resp.status_code == 200
    assert resp.json() == {"text": "transcript here"}


def test_stt_route_transcode_error_422(client, monkeypatch):
    import app.multimodal.router as r
    monkeypatch.setattr(
        r, "transcode_to_wav", AsyncMock(side_effect=service.TranscodeError("ffmpeg not found"))
    )
    resp = client.post(
        "/v1/multimodal/stt",
        files={"file": ("rec.webm", b"webmbytes", "audio/webm")},
    )
    assert resp.status_code == 422
    assert "ffmpeg" in resp.json()["detail"]
