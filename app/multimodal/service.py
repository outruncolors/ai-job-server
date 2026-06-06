"""Vision (image understanding) and Speech-to-Text via the multimodal preset.

The OpenAI-compatible chat client passes ``messages`` through verbatim, so these
helpers just assemble multimodal content parts (``image_url`` / ``input_audio``)
and read back ``choices[0].message.content``.
"""
from __future__ import annotations

import asyncio
import base64
from typing import Callable, Optional

from ..chain.llm_client import OpenAICompatibleLLMClient
from .swap import ensure_multimodal_loaded

DEFAULT_VISION_PROMPT = "Describe this image in detail."
# Gemma 4's audio path is trained on an ASR template that names the target
# language; a generic prompt that omits it makes the model drift to the wrong
# language (e.g. Chinese for English speech). We force English. See Google's
# audio docs: ai.google.dev/gemma/docs/capabilities/audio
DEFAULT_STT_PROMPT = (
    "Transcribe the following speech segment in English into English text. "
    "Follow these specific instructions for formatting the answer: "
    "Only output the transcription, with no newlines. "
    "When transcribing numbers, write the digits, i.e. write 1.7 and not "
    "one point seven, and write 3 instead of three."
)


class TranscodeError(RuntimeError):
    """Raised when ffmpeg fails to convert the uploaded audio to WAV."""


class ImageTranscodeError(RuntimeError):
    """Raised when ffmpeg fails to convert an uploaded image to PNG."""


# Image mimes llama.cpp's multimodal loader (stb_image) decodes natively. Notably
# absent: WebP — a data:image/webp URL makes the server 400 with "failed to load
# image", so anything outside this set is transcoded to PNG first.
VISION_NATIVE_MIMES = {"image/png", "image/jpeg", "image/jpg"}


def _content_text(choice: dict) -> str:
    try:
        content = choice["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"malformed multimodal response: {exc}") from exc
    if not content:
        raise RuntimeError("multimodal response has empty content")
    return content.strip()


async def transcode_to_wav(raw: bytes) -> bytes:
    """Convert arbitrary audio bytes (webm/opus, mp3, m4a, ogg, wav…) to
    16 kHz mono 16-bit WAV that llama.cpp's audio loader can decode.

    Streams via ffmpeg stdin/stdout so nothing touches disk.
    """
    if not raw:
        raise TranscodeError("empty audio upload")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", "pipe:0",
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:  # ffmpeg not installed
        raise TranscodeError(
            "ffmpeg not found — install it on this node to enable Speech-to-Text"
        ) from exc
    out, err = await proc.communicate(input=raw)
    if proc.returncode != 0 or not out:
        msg = (err or b"").decode("utf-8", "replace").strip() or "unknown error"
        raise TranscodeError(f"ffmpeg failed to decode audio: {msg}")
    return out


async def transcode_image_to_png(raw: bytes) -> bytes:
    """Decode arbitrary image bytes (webp, gif, …) and re-encode the first frame
    as PNG, which llama.cpp's image loader always accepts.

    Streams via ffmpeg stdin/stdout so nothing touches disk (mirrors
    :func:`transcode_to_wav`).
    """
    if not raw:
        raise ImageTranscodeError("empty image upload")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", "pipe:0",
            "-frames:v", "1",
            "-f", "image2pipe",
            "-vcodec", "png",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:  # ffmpeg not installed
        raise ImageTranscodeError(
            "ffmpeg not found — install it on this node to accept webp/other image formats"
        ) from exc
    out, err = await proc.communicate(input=raw)
    if proc.returncode != 0 or not out:
        msg = (err or b"").decode("utf-8", "replace").strip() or "unknown error"
        raise ImageTranscodeError(f"ffmpeg failed to decode image: {msg}")
    return out


def _emit_meta(choice: dict, on_meta: Optional[Callable[[dict], None]]) -> None:
    """Hand the response's ``finish_reason`` + token ``usage`` to ``on_meta`` so a
    caller (the job runner) can log why generation stopped — ``finish_reason=length``
    means it was truncated by a token/context limit, not a natural stop."""
    if on_meta is None:
        return
    on_meta({"finish_reason": choice.get("finish_reason"), "usage": choice.get("usage")})


async def run_vision(
    image_bytes: bytes,
    mime: str,
    prompt: str = "",
    *,
    on_meta: Optional[Callable[[dict], None]] = None,
) -> str:
    """Answer ``prompt`` about an image. Returns the model's text response."""
    prompt = (prompt or "").strip() or DEFAULT_VISION_PROMPT
    b64 = base64.b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }
    ]
    # Detailed descriptions are long; 1024 was a low ceiling. (The binding limit is
    # usually the preset's ctx_size/n_predict on the llm node — see on_meta logging.)
    cfg = await ensure_multimodal_loaded(temperature=0.4, max_tokens=4096)
    choice = await OpenAICompatibleLLMClient().chat(messages, cfg)
    _emit_meta(choice, on_meta)
    return _content_text(choice)


async def run_stt(
    wav_bytes: bytes,
    prompt: str = "",
    *,
    on_meta: Optional[Callable[[dict], None]] = None,
) -> str:
    """Transcribe 16 kHz mono WAV audio. Returns the transcript text."""
    prompt = (prompt or "").strip() or DEFAULT_STT_PROMPT
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
            ],
        }
    ]
    # Deterministic decode; allow more tokens for long transcripts.
    cfg = await ensure_multimodal_loaded(temperature=0.0, max_tokens=4096)
    choice = await OpenAICompatibleLLMClient().chat(messages, cfg)
    _emit_meta(choice, on_meta)
    return _content_text(choice)
