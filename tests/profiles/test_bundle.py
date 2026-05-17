from __future__ import annotations

import json
import zipfile

import pytest

from app import voice_presets as voice_presets_mod
from app.profiles.bundle import pack_profile, unpack_profile
from app.profiles.importer import apply_master_profile
from app.profiles.models import (
    SCHEMA_VERSION,
    MasterProfile,
    ProfileAsset,
    VoicePresetEntry,
)


def _profile_with_two_assets() -> MasterProfile:
    # Seed two voice presets so the bundle exercises multiple assets.
    voice_presets_mod.save_preset("Alice", "narrator A", b"WAV-A")
    voice_presets_mod.save_preset("Bob", "narrator B", b"WAV-B")
    presets = voice_presets_mod.list_presets()
    return MasterProfile(
        name="snapshot",
        description="two-asset bundle",
        voice_presets=[VoicePresetEntry.model_validate(p) for p in presets],
        asset_manifest=[
            ProfileAsset(filename=p["wav_filename"], kind="voice_wav") for p in presets
        ],
    )


def test_pack_and_unpack_round_trip(tmp_path):
    profile = _profile_with_two_assets()
    bundle_path = tmp_path / "bundle.zip"

    pack_profile(profile, bundle_path)
    assert bundle_path.exists()

    # The zip contains master.json plus one entry under assets/voice_presets/ per asset.
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
    assert "master.json" in names
    for asset in profile.asset_manifest:
        assert f"assets/voice_presets/{asset.filename}" in names

    extract_dir = tmp_path / "extracted"
    restored, asset_dir = unpack_profile(bundle_path, extract_to=extract_dir)

    assert restored.model_dump() == profile.model_dump()
    assert asset_dir == extract_dir / "assets" / "voice_presets"
    for asset in profile.asset_manifest:
        wav_path = asset_dir / asset.filename
        assert wav_path.exists()
        assert wav_path.read_bytes() in (b"WAV-A", b"WAV-B")


def test_unpack_into_tempdir_when_extract_to_not_given(tmp_path):
    profile = _profile_with_two_assets()
    bundle_path = tmp_path / "bundle.zip"
    pack_profile(profile, bundle_path)

    restored, asset_dir = unpack_profile(bundle_path)
    try:
        assert restored.name == "snapshot"
        assert asset_dir.is_absolute()
        assert asset_dir.exists()
        # Both assets are present in the temp extraction.
        for asset in profile.asset_manifest:
            assert (asset_dir / asset.filename).exists()
    finally:
        import shutil

        shutil.rmtree(asset_dir.parent.parent, ignore_errors=True)


def test_round_trip_feeds_importer_directly(tmp_path, monkeypatch):
    """End-to-end: pack a profile, unpack, hand asset_dir to apply_master_profile."""
    profile = _profile_with_two_assets()
    bundle_path = tmp_path / "bundle.zip"
    pack_profile(profile, bundle_path)

    # Now wipe the source voice_presets dir and re-import from the bundle.
    import shutil

    shutil.rmtree(voice_presets_mod.PRESETS_DIR, ignore_errors=True)

    restored, asset_dir = unpack_profile(bundle_path, extract_to=tmp_path / "extract")
    report = apply_master_profile(restored, mode="replace", asset_source=asset_dir)

    assert report.assets_copied == len(profile.asset_manifest)
    assert report.asset_warnings == []
    for asset in profile.asset_manifest:
        wav = voice_presets_mod.PRESETS_DIR / asset.filename
        assert wav.exists()


def test_pack_missing_source_asset_raises(tmp_path):
    """Reference an asset whose source file does not exist on disk."""
    profile = MasterProfile(
        name="broken",
        voice_presets=[
            VoicePresetEntry(id="vp1", name="X", wav_filename="ghost.wav")
        ],
        asset_manifest=[ProfileAsset(filename="ghost.wav", kind="voice_wav")],
    )
    with pytest.raises(FileNotFoundError, match="ghost.wav"):
        pack_profile(profile, tmp_path / "out.zip")


def test_unpack_rejects_unsupported_schema_version(tmp_path):
    bundle_path = tmp_path / "wrong.zip"
    bad_manifest = {"schema_version": "999", "name": "future"}
    with zipfile.ZipFile(bundle_path, "w") as zf:
        zf.writestr("master.json", json.dumps(bad_manifest))
    with pytest.raises(ValueError, match="schema_version"):
        unpack_profile(bundle_path, extract_to=tmp_path / "ex")


def test_unpack_rejects_bundle_without_manifest(tmp_path):
    bundle_path = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(bundle_path, "w") as zf:
        zf.writestr("assets/voice_presets/x.wav", b"x")
    with pytest.raises(ValueError, match="master.json"):
        unpack_profile(bundle_path, extract_to=tmp_path / "ex")


def test_unpack_rejects_zip_slip(tmp_path):
    bundle_path = tmp_path / "slip.zip"
    manifest = {"schema_version": SCHEMA_VERSION, "name": "x"}
    with zipfile.ZipFile(bundle_path, "w") as zf:
        zf.writestr("master.json", json.dumps(manifest))
        zf.writestr("../escape.wav", b"bad")
    with pytest.raises(ValueError, match="unsafe path"):
        unpack_profile(bundle_path, extract_to=tmp_path / "ex")


def test_unpack_empty_profile_creates_empty_asset_dir(tmp_path):
    profile = MasterProfile(name="empty")
    bundle_path = tmp_path / "bundle.zip"
    pack_profile(profile, bundle_path)

    restored, asset_dir = unpack_profile(bundle_path, extract_to=tmp_path / "ex")
    assert restored.model_dump() == profile.model_dump()
    assert asset_dir.is_dir()
    assert list(asset_dir.iterdir()) == []
