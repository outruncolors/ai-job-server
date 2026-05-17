"""Pack and unpack a MasterProfile + its binary assets as a .zip bundle.

Bundle layout:

    master.json                         (UTF-8 JSON, MasterProfile)
    assets/voice_presets/<wav_filename> (one entry per asset_manifest item)

`pack_profile` pulls source files via `list_required_assets`. `unpack_profile`
validates `schema_version`, extracts under a temp dir, and returns
`(MasterProfile, asset_dir)` where `asset_dir` matches the flat layout the
importer expects (one wav per filename, no subdirs).

Cleanup of the extraction directory is the caller's responsibility when no
`extract_to` is supplied; use `shutil.rmtree` after the import completes.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple

from .exporter import list_required_assets
from .models import SCHEMA_VERSION, MasterProfile

_MANIFEST_NAME = "master.json"
_ASSET_PREFIX = "assets/voice_presets"


def pack_profile(profile: MasterProfile, out_path: Path) -> Path:
    """Write a profile bundle to `out_path` and return the same path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sources_by_name = {p.name: p for p in list_required_assets(profile)}

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_MANIFEST_NAME, profile.model_dump_json(indent=2))
        for asset in profile.asset_manifest:
            if asset.kind != "voice_wav":
                continue
            src = sources_by_name.get(asset.filename)
            if src is None or not src.exists():
                raise FileNotFoundError(
                    f"profile references {asset.filename!r} but the source file is missing"
                )
            zf.write(src, arcname=f"{_ASSET_PREFIX}/{asset.filename}")
    return out_path


def _safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """zipfile.extractall with a zip-slip guard."""
    dest_resolved = dest.resolve()
    for name in zf.namelist():
        target = (dest / name).resolve()
        try:
            target.relative_to(dest_resolved)
        except ValueError as exc:
            raise ValueError(f"unsafe path in bundle: {name!r}") from exc
    zf.extractall(dest)


def unpack_profile(
    zip_path: Path,
    extract_to: Optional[Path] = None,
) -> Tuple[MasterProfile, Path]:
    """Extract a bundle and return `(profile, asset_dir)`.

    `asset_dir` is the absolute path to `assets/voice_presets/` inside the
    extraction tree — the directory the importer's `asset_source` expects.
    """
    zip_path = Path(zip_path)
    if extract_to is None:
        extract_to = Path(tempfile.mkdtemp(prefix="profile-bundle-"))
    else:
        extract_to = Path(extract_to)
        extract_to.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        if _MANIFEST_NAME not in zf.namelist():
            raise ValueError(f"bundle missing {_MANIFEST_NAME}")
        manifest_bytes = zf.read(_MANIFEST_NAME)
        _safe_extractall(zf, extract_to)

    manifest = json.loads(manifest_bytes)
    schema_version = manifest.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported profile schema_version: {schema_version!r} "
            f"(expected {SCHEMA_VERSION!r})"
        )

    profile = MasterProfile.model_validate(manifest)
    asset_dir = extract_to / _ASSET_PREFIX
    asset_dir.mkdir(parents=True, exist_ok=True)
    return profile, asset_dir
