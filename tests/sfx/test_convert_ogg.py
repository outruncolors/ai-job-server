"""scripts/convert_ogg_to_wav.py — manifest-driven OGG→WAV transcode."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

sf = pytest.importorskip("soundfile")

_ROOT = Path(__file__).resolve().parents[2]


def _load_converter():
    spec = importlib.util.spec_from_file_location(
        "convert_ogg_to_wav", _ROOT / "scripts" / "convert_ogg_to_wav.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


conv = _load_converter()


def _manifest(pack_id: str, item_path: str) -> dict:
    return {
        "schema_version": 1, "type": "sfx_pack", "id": pack_id, "binding": "global",
        "domain": "x", "display_name": "X",
        "profiles": [{"id": "_global", "display_name": "Global", "attributes": {}, "items": [
            {"id": "x_clip_01", "category": "c", "description": "c", "tags": ["c"],
             "path": item_path, "duration_ms": 1, "weight": 1.0, "domain": "x",
             "source": {"filename": "foo.ogg"}}]}],
    }


def _make_pack(tmp_path: Path, pack_id="test_pack"):
    root = tmp_path / "sfx"
    src_rel = "Vendor Pack/foo.ogg"
    src = root / src_rel
    src.parent.mkdir(parents=True, exist_ok=True)
    sig = (0.2 * np.sin(2 * np.pi * 220 * np.arange(4410) / 8000)).astype("float32")
    sf.write(str(src), sig, 8000, format="OGG", subtype="VORBIS")
    man = root / "normalized" / pack_id / "manifest.json"
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text(json.dumps(_manifest(pack_id, src_rel)), encoding="utf-8")
    return root, man, src_rel


def test_convert_repoints_manifest(tmp_path):
    root, man, src_rel = _make_pack(tmp_path)

    assert conv.convert_pack(man, root, dry_run=False) == (1, 0)

    item = json.loads(man.read_text())["profiles"][0]["items"][0]
    assert item["path"] == "normalized/test_pack/files/x_clip_01.wav"
    wav = root / item["path"]
    assert wav.exists() and wav.read_bytes()[:4] == b"RIFF"
    assert item["sample_rate"] == 8000 and item["channels"] == 1
    assert item["duration_ms"] > 0
    assert item["source"]["converted_from"] == src_rel
    assert item["source"]["filename"] == "x_clip_01.wav"

    # The vendor original is untouched, and a second pass is a no-op.
    assert (root / src_rel).exists()
    assert conv.convert_pack(man, root, dry_run=False) == (0, 0)


def test_dry_run_writes_nothing(tmp_path):
    root, man, _ = _make_pack(tmp_path)
    before = man.read_text()

    assert conv.convert_pack(man, root, dry_run=True) == (1, 0)

    assert man.read_text() == before                       # manifest untouched
    assert not (root / "normalized" / "test_pack" / "files").exists()  # no wav written
