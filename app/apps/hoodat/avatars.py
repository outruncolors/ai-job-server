"""Avatar handling for Hoodat characters.

Two paths, both ending with the image stored at `config/hoodat/avatars/<id>.png`
and the character's `avatar_path` pointing at the serve endpoint:

- **generate** — build a `{{var.*}}`-templated image prompt from the character's
  appearance (Prompt Pal entry `avatar.image_prompt`, composed mechanically),
  run the existing ComfyUI `image` workflow via `execute_image_job`, then copy
  the produced image out of the job dir.
- **upload** — accept raw image bytes and store them.

`execute_image_job` is imported by name so tests can monkeypatch it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ...comfyui.config import get_config as get_comfy_config
from ...comfyui.manager import get_manager as get_comfy_manager
from ...comfyui.runner import execute_image_job
from ...jobs import create_job, find_job_dir
from ...models import ImageJobRequest
from ...prompt_pal.service import get_text
from . import characters_store
from .prompts import avatar_prompt_variables

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AVATARS_DIR: Path = PROJECT_ROOT / "config" / "hoodat" / "avatars"
AVATAR_JOB_TYPE = "hoodat_avatar"

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


class AvatarError(Exception):
    """Raised when avatar generation/storage fails."""


def _avatar_file(character_id: str) -> Path:
    return AVATARS_DIR / f"{character_id}.png"


def avatar_file_if_exists(character_id: str) -> Optional[Path]:
    p = _avatar_file(character_id)
    return p if p.exists() else None


def _avatar_url(character_id: str) -> str:
    return f"/v1/apps/hoodat/characters/{character_id}/avatar"


def _store_bytes(character_id: str, data: bytes) -> str:
    """Write avatar bytes, set `avatar_path`, return the serve URL."""
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _avatar_file(character_id)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    characters_store.update_character_fields(character_id, {"avatar_path": _avatar_url(character_id)})
    return _avatar_url(character_id)


def build_avatar_prompt(character: dict) -> str:
    return get_text("hoodat", "avatar.image_prompt", variables=avatar_prompt_variables(character))


def _find_image_artifact(job_dir: Path) -> Optional[Path]:
    af = job_dir / "artifacts.json"
    if not af.exists():
        return None
    try:
        artifacts = json.loads(af.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for entry in artifacts:
        name = entry.get("filename", "")
        if name.lower().endswith(_IMAGE_EXTS):
            candidate = job_dir / name
            if candidate.exists():
                return candidate
    return None


async def generate_avatar(character_id: str) -> tuple[str, str]:
    """Generate an avatar via ComfyUI. Returns `(avatar_url, job_id)`."""
    character = characters_store.get_character(character_id)
    if character is None:
        raise AvatarError(f"character not found: {character_id}")

    prompt = build_avatar_prompt(character)
    request = ImageJobRequest(workflow="image", prompt=prompt)
    status = create_job(AVATAR_JOB_TYPE, request.model_dump(), prompt)
    job_id = status["job_id"]
    job_dir = find_job_dir(job_id)
    if job_dir is None:  # pragma: no cover
        raise AvatarError("job directory disappeared after creation")

    await execute_image_job(job_id, job_dir, request, get_comfy_config(), get_comfy_manager())

    img = _find_image_artifact(job_dir)
    if img is None:
        raise AvatarError("image generation produced no output")
    url = _store_bytes(character_id, img.read_bytes())
    return url, job_id


def save_uploaded_avatar(character_id: str, data: bytes, content_type: Optional[str]) -> str:
    """Store an uploaded avatar image. Returns the serve URL."""
    if characters_store.get_character(character_id) is None:
        raise AvatarError(f"character not found: {character_id}")
    if not data:
        raise AvatarError("empty upload")
    if content_type and not content_type.startswith("image/"):
        raise AvatarError(f"not an image: {content_type}")
    return _store_bytes(character_id, data)
