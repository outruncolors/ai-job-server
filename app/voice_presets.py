from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .omnivoice.config import PROJECT_ROOT

PRESETS_DIR: Path = PROJECT_ROOT / "config" / "voice_presets"
INDEX_PATH: Path = PRESETS_DIR / "index.json"


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _unique_name(base_name: str, existing_names: list[str]) -> str:
    if base_name not in existing_names:
        return base_name
    n = 2
    while f"{base_name} ({n})" in existing_names:
        n += 1
    return f"{base_name} ({n})"


def list_presets() -> list[dict]:
    return _read_index()


def get_preset(preset_id: str) -> Optional[dict]:
    for p in _read_index():
        if p["id"] == preset_id:
            return p
    return None


def save_preset(name: str, caption: str, wav_bytes: bytes) -> dict:
    entries = _read_index()
    existing_names = [e["name"] for e in entries]
    final_name = _unique_name(name, existing_names)

    preset_id = str(uuid.uuid4())
    wav_filename = f"{preset_id}.wav"
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    (PRESETS_DIR / wav_filename).write_bytes(wav_bytes)

    entry = {
        "id": preset_id,
        "name": final_name,
        "caption": caption,
        "wav_filename": wav_filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entries.append(entry)
    _write_index(entries)
    return entry


def save_preset_from_job(job_id: str, name: str, caption: str) -> dict:
    from .jobs import find_job_dir  # local import to avoid circular dependency

    job_dir = find_job_dir(job_id)
    if job_dir is None:
        raise FileNotFoundError(f"Job {job_id!r} not found")
    output_wav = job_dir / "output.wav"
    if not output_wav.exists():
        raise FileNotFoundError(f"output.wav missing for job {job_id!r}")
    return save_preset(name, caption, output_wav.read_bytes())


def delete_preset(preset_id: str) -> bool:
    entries = _read_index()
    target = next((e for e in entries if e["id"] == preset_id), None)
    if target is None:
        return False
    wav_path = PRESETS_DIR / target["wav_filename"]
    if wav_path.exists():
        wav_path.unlink()
    _write_index([e for e in entries if e["id"] != preset_id])
    return True


def resolve_preset_wav(preset_id: str) -> Optional[Path]:
    entry = get_preset(preset_id)
    if entry is None:
        return None
    wav_path = PRESETS_DIR / entry["wav_filename"]
    return wav_path if wav_path.exists() else None
