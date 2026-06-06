"""Routes for the Vision and Speech-to-Text features.

Not capability-gated: these run on the web node and route to the llm node via
the chain executor's resolve helpers, so gating on ``llm`` would wrongly 503
the web node. A missing/unreachable llm node surfaces as a 503 below instead.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..chain.llm_swap import LLMSwapError
from .service import TranscodeError, run_stt, run_vision, transcode_to_wav

_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

router = APIRouter(prefix="/v1/multimodal", tags=["multimodal"])


@router.post("/vision")
async def vision(
    file: UploadFile = File(...),
    prompt: str = Form(""),
) -> dict:
    """Understand an uploaded image. Returns ``{"text": <model answer>}``."""
    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported image content_type: {content_type or 'unknown'}",
        )
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="empty image upload")
    try:
        text = await run_vision(image_bytes, content_type, prompt)
    except LLMSwapError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"text": text}


@router.post("/stt")
async def stt(
    file: UploadFile = File(...),
    prompt: str = Form(""),
) -> dict:
    """Transcribe uploaded/recorded audio. Returns ``{"text": <transcript>}``."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="empty audio upload")
    try:
        wav_bytes = await transcode_to_wav(raw)
    except TranscodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        text = await run_stt(wav_bytes, prompt)
    except LLMSwapError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"text": text}
