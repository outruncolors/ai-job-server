#!/usr/bin/env python
"""Normalize a vendor sound pack into the project's standard SFX manifest.

Two packing conventions are supported, selected by ``--binding``:

* ``identity`` — per-speaker emote packs (e.g. Articulated Universal Emotes). Each
  vendor speaker folder (``EMOTE Ashley, Woman, 40s``) is mapped to one standard
  identity enum (gender x age-band, see app.sfx.models.Identity). Items are grouped
  under that identity. For every identity profile the importer additionally writes
  ``_low`` / ``_high`` pitch+formant-shifted variant profiles (PSOLA via parselmouth).
* ``global`` — flat category-folder packs (e.g. a lewd FX pack). Items are grouped
  under a single ``_global`` profile and tagged with a ``domain``. No pitch variants.

Item ``path`` values are stored relative to SFX_ROOT so vendor originals are read in
place and never copied. The only generated audio is the pitch derivatives, written to
``normalized/<pack_id>/files/``.

Usage::

    .venv/bin/python scripts/import_sfx_pack.py \
        "/opt/ai-stack/sfx/Articulated--Universal_Emotes--Separated_01" \
        --pack-id universal_emotes --binding identity --display-name "Universal Emotes"

    .venv/bin/python scripts/import_sfx_pack.py \
        "/opt/ai-stack/sfx/Shinlalala's Lewd Sound Pack" \
        --pack-id shinlalala_lewd --binding global --domain lewd \
        --display-name "Shinlalala Lewd Pack"
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import struct
import sys
import wave
from pathlib import Path
from typing import Optional

# Make ``app`` importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sfx.models import (  # noqa: E402
    AGE_BAND_BY_TOKEN,
    PRESENTATION_BY_GENDER,
    SFX_SCHEMA_VERSION,
    identity_for,
)

# --- pitch variant ratios (modest; see docs/tools/sfx.md) -------------------
# Move pitch and formants together so a shift reads as a plausibly larger/smaller
# speaker rather than a chipmunk (pure resample) or an unnatural timbre (pitch-only).
PITCH_VARIANTS = {
    "low": {"formant": 0.92, "pitch": 0.87},
    "high": {"formant": 1.10, "pitch": 1.15},
}
DERIVATIVE_SAMPLE_RATE = 48000  # downsample derivatives to keep size sane

# --- vendor CatID prefix -> canonical category ------------------------------
CATEGORY_BY_PREFIX = {
    "FOODDrnk": "drink",
    "FOODEat": "eat",
    "HMNBrth": "breath",
    "HMNCough": "cough",
    "HMNKiss": "kiss",
    "HMNSneez": "sneeze",
    "VOXCheer": "cheer",
    "VOXChld": "reaction",
    "VOXCry": "cry",
    "VOXEfrt": "effort",
    "VOXFem": "reaction",
    "VOXLaff": "laugh",
    "VOXMale": "reaction",
    "VOXReac": "reaction",
    "VOXScrm": "scream",
}


def slug(text: str) -> str:
    # Split camelCase boundaries ("DryPlaps" -> "Dry Plaps") before lowercasing.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", spaced.lower())).strip("_")


def is_audio(p: Path) -> bool:
    return (
        p.is_file()
        and not p.name.startswith("._")  # macOS AppleDouble sidecars
        and p.suffix.lower() in (".wav", ".ogg")
    )


# --- duration helpers -------------------------------------------------------
def wav_duration_ms(path: Path) -> Optional[int]:
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as w:
            frames, rate = w.getnframes(), w.getframerate()
        return int(round(frames / rate * 1000)) if rate else None
    except Exception:
        return None


def ogg_duration_ms(path: Path) -> Optional[int]:
    """Duration from the Ogg/Vorbis stream: last page granulepos / sample rate."""
    try:
        data = path.read_bytes()
        # Sample rate from the Vorbis identification header (packet type 0x01).
        idx = data.find(b"\x01vorbis")
        if idx < 0:
            return None
        rate = struct.unpack_from("<I", data, idx + 12)[0]
        # Highest granule position across all Ogg pages.
        granule, off = 0, 0
        while True:
            off = data.find(b"OggS", off)
            if off < 0:
                break
            granule = max(granule, struct.unpack_from("<q", data, off + 6)[0])
            off += 4
        return int(round(granule / rate * 1000)) if rate and granule > 0 else None
    except Exception:
        return None


def duration_ms(path: Path) -> Optional[int]:
    return wav_duration_ms(path) if path.suffix.lower() == ".wav" else ogg_duration_ms(path)


# --- filename parsing (identity packs) --------------------------------------
def parse_emote_filename(name: str) -> Optional[dict]:
    """``VOXCry_Emote Chloe, Teen, Sadness Cry Long 02_ASD.wav`` ->
    {category, description, tags}. Returns None when the prefix is unknown."""
    stem = name.rsplit(".", 1)[0]
    parts = stem.split("_")
    if len(parts) < 2:
        return None
    prefix = parts[0]
    category = CATEGORY_BY_PREFIX.get(prefix)
    if category is None:
        return None
    descriptor = parts[1]  # "Emote Chloe, Teen, Sadness Cry Long 02"
    segs = [s.strip() for s in descriptor.split(",")]
    tail = segs[-1] if segs else descriptor
    tail = re.sub(r"\b\d+\b", "", tail).strip()  # drop the take number
    description = tail or category
    tags = sorted({w.lower() for w in re.findall(r"[A-Za-z]+", tail)} | {category})
    return {"category": category, "description": description, "tags": tags}


def parse_speaker_folder(name: str) -> Optional[tuple[str, str]]:
    """``EMOTE Ashley, Woman, 40s`` -> (gender, age_token), else None."""
    segs = [s.strip() for s in name.split(",")]
    if len(segs) < 3:
        return None
    return segs[1], segs[2]  # gender, age token


# --- pitch shift ------------------------------------------------------------
def write_pitch_variant(src: Path, dst: Path, formant: float, pitch: float) -> bool:
    """PSOLA pitch+formant shift via Praat 'Change gender'. Idempotent."""
    if dst.exists():
        return True
    try:
        import parselmouth
        from parselmouth.praat import call

        sound = parselmouth.Sound(str(src))
        if sound.sampling_frequency > DERIVATIVE_SAMPLE_RATE:
            sound = call(sound, "Resample", DERIVATIVE_SAMPLE_RATE, 50)
        shifted = call(sound, "Change gender", 75, 600, formant, 0, pitch, 1.0)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shifted.save(str(dst), "WAV")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ! pitch variant failed for {src.name}: {exc}", file=sys.stderr)
        return False


# --- importers --------------------------------------------------------------
def import_identity(vendor: Path, pack_id: str, sfx_root: Path, make_pitch: bool,
                    limit: Optional[int]) -> list[dict]:
    profiles: dict[str, dict] = {}
    counters: dict[tuple[str, str], int] = {}
    for folder in sorted(vendor.rglob("EMOTE *")):
        if not folder.is_dir():
            continue
        parsed = parse_speaker_folder(folder.name)
        if parsed is None:
            print(f"  - skip unparseable folder: {folder.name}", file=sys.stderr)
            continue
        gender, age = parsed
        identity = identity_for(gender, age)
        if identity is None:
            print(f"  - skip unmapped identity: {folder.name} ({gender}, {age})", file=sys.stderr)
            continue
        prof = profiles.setdefault(identity, _new_identity_profile(identity, gender, age))
        if folder.name not in prof["source_profiles"]:
            prof["source_profiles"].append(folder.name)
        files = [f for f in sorted(folder.iterdir()) if is_audio(f)]
        if limit:
            files = files[:limit]
        for f in files:
            meta = parse_emote_filename(f.name)
            if meta is None:
                continue
            key = (identity, meta["category"])
            counters[key] = counters.get(key, 0) + 1
            iid = f"{identity}_{meta['category']}_{counters[key]:02d}"
            prof["items"].append({
                "id": iid,
                "category": meta["category"],
                "description": meta["description"],
                "tags": meta["tags"],
                "path": _rel(f, sfx_root),
                "duration_ms": duration_ms(f),
                "weight": 1.0,
                "source": {"filename": f.name},
            })

    out = list(profiles.values())
    if make_pitch:
        out += _build_pitch_profiles(out, pack_id, sfx_root)
    return out


def _new_identity_profile(identity: str, gender: str, age: str) -> dict:
    return {
        "id": identity,
        "display_name": identity.replace("_", " ").title(),
        "attributes": {
            "presentation": PRESENTATION_BY_GENDER.get(gender, "unknown"),
            "age_band": AGE_BAND_BY_TOKEN.get(age, "unknown"),
            "pitch": "base",
        },
        "source_profiles": [],
        "items": [],
    }


def _build_pitch_profiles(base_profiles: list[dict], pack_id: str, sfx_root: Path) -> list[dict]:
    files_dir = sfx_root / "normalized" / pack_id / "files"
    derived: list[dict] = []
    for base in base_profiles:
        for variant, ratios in PITCH_VARIANTS.items():
            prof = {
                "id": f"{base['id']}_{variant}",
                "display_name": f"{base['display_name']} ({variant})",
                "attributes": {**base["attributes"], "pitch": variant},
                "source_profiles": list(base["source_profiles"]),
                "items": [],
            }
            for item in base["items"]:
                src = sfx_root / item["path"]
                dst = files_dir / f"{item['id']}_{variant}.wav"
                if not write_pitch_variant(src, dst, ratios["formant"], ratios["pitch"]):
                    continue
                prof["items"].append({
                    **item,
                    "id": f"{item['id']}_{variant}",
                    "path": _rel(dst, sfx_root),
                    "duration_ms": item["duration_ms"],
                    "source": {**item["source"], "derived_from": item["id"], "variant": variant},
                })
            print(f"  ~ pitch profile {prof['id']}: {len(prof['items'])} items")
            derived.append(prof)
    return derived


def import_global(vendor: Path, domain: str, sfx_root: Path, limit: Optional[int]) -> list[dict]:
    items: list[dict] = []
    counters: dict[str, int] = {}
    for folder in sorted(p for p in vendor.iterdir() if p.is_dir() and not p.name.startswith("._")):
        category = slug(folder.name)
        files = [f for f in sorted(folder.iterdir()) if is_audio(f)]
        if limit:
            files = files[:limit]
        for f in files:
            counters[category] = counters.get(category, 0) + 1
            items.append({
                "id": f"{domain}_{category}_{counters[category]:02d}",
                "category": category,
                "domain": domain,
                "description": folder.name,
                "tags": sorted({category, domain}),
                "path": _rel(f, sfx_root),
                "duration_ms": duration_ms(f),
                "weight": 1.0,
                "source": {"filename": f.name},
            })
    return [{"id": "_global", "display_name": "Global", "attributes": {}, "items": items}]


def _rel(path: Path, sfx_root: Path) -> str:
    return str(path.resolve().relative_to(sfx_root.resolve()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("vendor_dir")
    ap.add_argument("--pack-id", required=True)
    ap.add_argument("--binding", required=True, choices=["identity", "global"])
    ap.add_argument("--domain", default=None, help="required for --binding global")
    ap.add_argument("--display-name", default=None)
    ap.add_argument("--sfx-root", default="/opt/ai-stack/sfx")
    ap.add_argument("--no-pitch", action="store_true", help="skip pitch variants (identity packs)")
    ap.add_argument("--limit", type=int, default=None, help="cap files per folder (testing)")
    args = ap.parse_args()

    vendor = Path(args.vendor_dir)
    sfx_root = Path(args.sfx_root)
    if not vendor.is_dir():
        print(f"vendor dir not found: {vendor}", file=sys.stderr)
        return 2
    if args.binding == "global" and not args.domain:
        print("--domain is required for --binding global", file=sys.stderr)
        return 2

    print(f"Importing {args.pack_id} ({args.binding}) from {vendor.name}")
    if args.binding == "identity":
        profiles = import_identity(vendor, args.pack_id, sfx_root, not args.no_pitch, args.limit)
    else:
        profiles = import_global(vendor, args.domain, sfx_root, args.limit)

    manifest = {
        "schema_version": SFX_SCHEMA_VERSION,
        "type": "sfx_pack",
        "id": args.pack_id,
        "binding": args.binding,
        "display_name": args.display_name or args.pack_id.replace("_", " ").title(),
        "source": {"vendor_dir": vendor.name},
    }
    if args.binding == "global":
        manifest["domain"] = args.domain
    manifest["profiles"] = profiles

    out_dir = sfx_root / "normalized" / args.pack_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(len(p["items"]) for p in profiles)
    print(f"Wrote {out_path}  ({len(profiles)} profiles, {total} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
