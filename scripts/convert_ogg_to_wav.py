#!/usr/bin/env python3
"""Transcode the SFX OGG clips to WAV so synthesis can use them.

The runtime has no Vorbis decoder usable by synthesis (parselmouth can't read
OGG, ``audioop`` is gone in 3.13), so SFX synthesis is WAV-only. This one-off
decodes the OGG packs ahead of time via libsndfile (the ``soundfile`` package).

The work is **manifest-driven**: for each pack under ``SFX_ROOT/normalized`` it
finds every item whose ``path`` ends in ``.ogg``, decodes the referenced vendor
file, and writes a 16-bit PCM WAV into that pack's writable
``normalized/<pack_id>/files/`` derivatives directory (the same place pitch
variants already live), then repoints the manifest item at the new WAV and
refreshes its ``duration_ms`` / ``sample_rate`` / ``channels``.

Why not literally in place? The vendor source folders (e.g. ``Shinlalala's Lewd
Sound Pack/``) are read-only to the app user, so the originals are left as-is and
the converted WAVs live alongside the other generated derivatives. Idempotent:
once a manifest points at a WAV there's nothing left to convert.

Usage:
    .venv/bin/python scripts/convert_ogg_to_wav.py [--dry-run] [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import wave
from pathlib import Path

import soundfile as sf

DEFAULT_ROOT = Path(os.environ.get("SFX_ROOT", "/opt/ai-stack/sfx"))


def _wav_meta(path: Path) -> tuple[int | None, int | None, int | None]:
    """(duration_ms, sample_rate, channels) for a WAV, or (None, None, None)."""
    try:
        with wave.open(str(path), "rb") as w:
            frames, rate, ch = w.getnframes(), w.getframerate(), w.getnchannels()
        return (int(round(frames / rate * 1000)) if rate else None, rate, ch)
    except Exception:
        return (None, None, None)


def convert_pack(manifest_path: Path, root: Path, *, dry_run: bool) -> tuple[int, int]:
    """Repoint a pack's .ogg items to freshly-decoded WAV derivatives.

    Returns (converted, failed)."""
    try:
        pack = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! skip unreadable manifest {manifest_path}: {exc}")
        return (0, 0)

    pack_id = manifest_path.parent.name
    files_dir = manifest_path.parent / "files"
    converted, failed = 0, 0

    for profile in pack.get("profiles", []):
        for item in profile.get("items", []):
            rel = item.get("path", "")
            if not rel.lower().endswith(".ogg"):
                continue
            src = root / rel
            if not src.exists():
                print(f"  ! missing source, skipping: {rel}")
                failed += 1
                continue

            dst_name = f"{item['id']}.wav"
            dst = files_dir / dst_name
            dst_rel = f"normalized/{pack_id}/files/{dst_name}"

            if not dry_run:
                try:
                    files_dir.mkdir(parents=True, exist_ok=True)
                    data, rate = sf.read(str(src), dtype="int16", always_2d=False)
                    sf.write(str(dst), data, rate, subtype="PCM_16")
                except Exception as exc:
                    print(f"  ! failed to convert {rel}: {exc}")
                    failed += 1
                    continue

            item["path"] = dst_rel
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            source.setdefault("converted_from", rel)
            source["filename"] = dst_name
            item["source"] = source
            if not dry_run:
                dur, srate, ch = _wav_meta(dst)
                if dur is not None:
                    item["duration_ms"] = dur
                if srate is not None:
                    item["sample_rate"] = srate
                if ch is not None:
                    item["channels"] = ch

            print(f"  {rel} -> {dst_rel}")
            converted += 1

    if converted and not dry_run:
        manifest_path.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    return converted, failed


def main() -> int:
    ap = argparse.ArgumentParser(description="Transcode SFX OGG clips to WAV derivatives.")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=f"SFX root (default {DEFAULT_ROOT})")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()

    root: Path = args.root
    if not root.exists():
        print(f"SFX root not found: {root}")
        return 1

    manifests = sorted(root.glob("normalized/*/manifest.json"))
    print(f"Scanning {len(manifests)} pack manifest(s) under {root}"
          + (" [dry-run]" if args.dry_run else ""))

    total_conv, total_fail = 0, 0
    for manifest_path in manifests:
        conv, fail = convert_pack(manifest_path, root, dry_run=args.dry_run)
        if conv or fail:
            print(f"  · {manifest_path.parent.name}: {conv} converted, {fail} failed")
        total_conv += conv
        total_fail += fail

    print(f"\nDone: {total_conv} clip(s) converted to WAV, {total_fail} failed.")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
