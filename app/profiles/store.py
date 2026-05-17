"""Named-profile store + active-profile marker.

Profiles live on disk under `config/profiles/<profile_id>/`:

    master.json                      (a MasterProfile, same layout as bundle.py)
    assets/voice_presets/<wav>       (one file per asset_manifest entry)

A sibling `config/profiles/index.json` holds the discoverable metadata
(id, name, description, created_at, updated_at). `config/profiles/active.json`
holds `{"active_id": "..."}` — empty/missing means no active profile.

`save_profile(name)` snapshots current live config into a new named profile.
`set_active(id)` applies a stored profile back to live config using the
importer in replace mode (so the running server reflects the chosen profile).
`delete_profile(id)` clears active if the deleted profile was active.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .bundle import _ASSET_PREFIX
from .exporter import build_master_profile, list_required_assets
from .importer import ImportReport, apply_master_profile
from .models import MasterProfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR: Path = PROJECT_ROOT / "config" / "profiles"
INDEX_PATH: Path = PROFILES_DIR / "index.json"
ACTIVE_PATH: Path = PROFILES_DIR / "active.json"
MASTER_FILENAME = "master.json"
ASSETS_SUBDIR = _ASSET_PREFIX  # "assets/voice_presets"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _write_index(entries: list[dict]) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _profile_dir(pid: str) -> Path:
    return PROFILES_DIR / pid


def _master_path(pid: str) -> Path:
    return _profile_dir(pid) / MASTER_FILENAME


def _asset_dir(pid: str) -> Path:
    return _profile_dir(pid) / ASSETS_SUBDIR


def _unique_name(base: str, existing_names: list[str]) -> str:
    if base not in existing_names:
        return base
    n = 2
    while f"{base} ({n})" in existing_names:
        n += 1
    return f"{base} ({n})"


def list_profiles() -> list[dict]:
    return sorted(_read_index(), key=lambda e: e.get("created_at", ""))


def get_profile(pid: str) -> Optional[dict]:
    return next((e for e in _read_index() if e["id"] == pid), None)


def load_profile_master(pid: str) -> Optional[MasterProfile]:
    path = _master_path(pid)
    if not path.exists():
        return None
    return MasterProfile.model_validate_json(path.read_text(encoding="utf-8"))


def save_profile(name: str, description: str = "") -> dict:
    """Snapshot current live config into a new named profile on disk."""
    if not name or not name.strip():
        raise ValueError("name is required")
    name = name.strip()
    entries = _read_index()
    final_name = _unique_name(name, [e["name"] for e in entries])

    profile = build_master_profile(final_name, description)

    pid = str(uuid.uuid4())
    asset_dir = _asset_dir(pid)
    asset_dir.mkdir(parents=True, exist_ok=True)
    _master_path(pid).write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    for src in list_required_assets(profile):
        if src.exists():
            shutil.copyfile(src, asset_dir / src.name)

    now = _now_iso()
    entry = {
        "id": pid,
        "name": final_name,
        "description": description or "",
        "created_at": now,
        "updated_at": now,
    }
    entries.append(entry)
    _write_index(entries)
    return entry


def delete_profile(pid: str) -> bool:
    entries = _read_index()
    new_entries = [e for e in entries if e["id"] != pid]
    if len(new_entries) == len(entries):
        return False
    pd = _profile_dir(pid)
    if pd.exists():
        shutil.rmtree(pd)
    _write_index(new_entries)
    if get_active_id() == pid:
        clear_active()
    return True


def set_active(pid: str) -> ImportReport:
    """Apply a stored profile to live config and mark it active."""
    profile = load_profile_master(pid)
    if profile is None:
        raise FileNotFoundError(f"profile {pid!r} not found")
    report = apply_master_profile(profile, mode="replace", asset_source=_asset_dir(pid))
    _write_active(pid)
    return report


def get_active_id() -> Optional[str]:
    if not ACTIVE_PATH.exists():
        return None
    data = json.loads(ACTIVE_PATH.read_text(encoding="utf-8"))
    return data.get("active_id")


def get_active() -> Optional[dict]:
    pid = get_active_id()
    if pid is None:
        return None
    return get_profile(pid)


def _write_active(pid: str) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_PATH.write_text(json.dumps({"active_id": pid}), encoding="utf-8")


def clear_active() -> None:
    if ACTIVE_PATH.exists():
        ACTIVE_PATH.unlink()
