from __future__ import annotations

import pytest

from app.apps.hoodat import avatars
from app.apps.hoodat import characters_store as cs
from app.jobs import _update_artifacts


async def test_generate_avatar_copies_artifact(monkeypatch):
    char = cs.create_character({"name": "Ada", "appearance": {"hair_color": "red"}})

    async def fake_image(job_id, job_dir, request, config, manager):
        out = job_dir / "ComfyUI_0001.png"
        out.write_bytes(b"\x89PNG\r\n\x1a\nDATA")
        _update_artifacts(job_dir, out)

    monkeypatch.setattr(avatars, "execute_image_job", fake_image)

    url, job_id = await avatars.generate_avatar(char["id"])
    assert url.endswith(f"/{char['id']}/avatar")
    assert job_id
    # file copied into the avatars dir
    saved = avatars.avatar_file_if_exists(char["id"])
    assert saved is not None and saved.read_bytes().startswith(b"\x89PNG")
    # avatar_path persisted
    assert cs.get_character(char["id"])["avatar_path"] == url


async def test_generate_avatar_no_output_errors(monkeypatch):
    char = cs.create_character({"name": "Ada"})

    async def fake_image(job_id, job_dir, request, config, manager):
        pass  # produces nothing

    monkeypatch.setattr(avatars, "execute_image_job", fake_image)
    with pytest.raises(avatars.AvatarError):
        await avatars.generate_avatar(char["id"])


async def test_generate_avatar_missing_character(monkeypatch):
    with pytest.raises(avatars.AvatarError):
        await avatars.generate_avatar("nope")


def test_build_avatar_prompt_uses_appearance():
    char = cs.create_character({
        "name": "Ada", "age": 41, "sex": "female",
        "appearance": {
            "hair_color": "silver", "hair_details": "in a bun",
            "eye_color": "grey",
            "outfits": [
                {"name": "Off-duty", "top": "hoodie"},
                {"name": "Work", "top": "lab coat", "primary": True},
            ],
        },
    })
    prompt = avatars.build_avatar_prompt(char)
    # natural-language photographic portrait template, appearance woven in
    assert "41-year-old female" in prompt
    assert "silver in a bun" in prompt        # combined hair color + details
    assert "lab coat" in prompt               # from the PRIMARY outfit, not the first
    assert "photographic" in prompt and "85mm" in prompt
    assert "{{var." not in prompt  # all variables substituted


def test_build_avatar_prompt_sparse_character_is_grammatical():
    char = cs.create_character({"name": "Nyx"})  # almost everything empty
    prompt = avatars.build_avatar_prompt(char)
    assert "{{var." not in prompt
    assert "adult person" in prompt          # age/sex fallbacks
    assert ", , " not in prompt              # no dangling features clause
    assert "-year-old" not in prompt         # no empty age suffix


def test_save_uploaded_avatar_validates():
    char = cs.create_character({"name": "Ada"})
    with pytest.raises(avatars.AvatarError):
        avatars.save_uploaded_avatar(char["id"], b"", "image/png")
    with pytest.raises(avatars.AvatarError):
        avatars.save_uploaded_avatar(char["id"], b"x", "text/plain")
    url = avatars.save_uploaded_avatar(char["id"], b"\x89PNGdata", "image/png")
    assert url.endswith("/avatar")
