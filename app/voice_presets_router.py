from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .voice_presets import delete_preset, list_presets, save_preset, save_preset_from_job

router = APIRouter(prefix="/v1/voice-presets", tags=["voice-presets"])


class PresetEntry(BaseModel):
    id: str
    name: str
    caption: str
    wav_filename: str
    created_at: str


class FromJobRequest(BaseModel):
    job_id: str
    name: str
    caption: str = ""


@router.get("", response_model=list[PresetEntry])
def get_presets():
    return list_presets()


@router.post("", response_model=PresetEntry, status_code=201)
async def create_preset(
    file: UploadFile = File(...),
    name: str = Form(...),
    caption: str = Form(...),
):
    if not file.filename or not file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=422, detail="Only .wav files are accepted")
    wav_bytes = await file.read()
    entry = save_preset(name, caption, wav_bytes)
    return PresetEntry(**entry)


# must be declared before /{preset_id} so FastAPI matches the literal segment first
@router.post("/from-job", response_model=PresetEntry, status_code=201)
def create_preset_from_job(req: FromJobRequest):
    try:
        entry = save_preset_from_job(req.job_id, req.name, req.caption)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PresetEntry(**entry)


@router.delete("/{preset_id}", status_code=200)
def remove_preset(preset_id: str):
    if not delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"deleted": preset_id}
