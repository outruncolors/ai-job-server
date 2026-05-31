"""Discovery, lookup and safe file serving for normalized SFX packs.

Packs live under ``SFX_ROOT/normalized/<pack_id>/manifest.json`` (env
``SFX_ROOT``, default ``/opt/ai-stack/sfx``). Item ``path`` values are relative
to ``SFX_ROOT``; vendor originals are read in place and only pitch derivatives
are generated (see scripts/import_sfx_pack.py).
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Optional

from .models import SfxItem, SfxPack

SFX_ROOT: Path = Path(os.environ.get("SFX_ROOT", "/opt/ai-stack/sfx"))

# Number of sample descriptions surfaced per category in the chooser summary.
_SUMMARY_SAMPLES = 4


def _normalized_dir() -> Path:
    return SFX_ROOT / "normalized"


def list_packs() -> list[SfxPack]:
    """Every discoverable pack, sorted by id. Unreadable manifests are skipped."""
    root = _normalized_dir()
    if not root.is_dir():
        return []
    packs: list[SfxPack] = []
    for manifest in sorted(root.glob("*/manifest.json")):
        try:
            packs.append(SfxPack.model_validate_json(manifest.read_text(encoding="utf-8")))
        except Exception:
            continue
    return packs


def get_pack(pack_id: str) -> Optional[SfxPack]:
    manifest = _normalized_dir() / pack_id / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        return SfxPack.model_validate_json(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_profile(pack_id: str, profile_id: str):
    pack = get_pack(pack_id)
    if pack is None:
        return None
    for profile in pack.profiles:
        if profile.id == profile_id:
            return profile
    return None


# A candidate is one item plus where it came from, so a resolved pick can be
# traced back to its pack/profile.
PoolEntry = tuple[str, str, SfxItem]  # (pack_id, profile_id, item)


def list_identity_profiles() -> list[dict]:
    """Every selectable identity profile across identity packs (base + pitch
    variants), merged by profile id. Drives the Hoodat identity dropdown."""
    merged: dict[str, dict] = {}
    for pack in list_packs():
        if pack.binding != "identity":
            continue
        for profile in pack.profiles:
            entry = merged.setdefault(profile.id, {
                "value": profile.id,
                "label": profile.display_name or profile.id.replace("_", " ").title(),
                "pitch": profile.attributes.get("pitch", "base"),
                "packs": [],
            })
            if pack.id not in entry["packs"]:
                entry["packs"].append(pack.id)
    order = {"base": 0, "low": 1, "high": 2}
    return sorted(merged.values(),
                  key=lambda e: (e["value"].split("_")[0], order.get(e["pitch"], 9), e["value"]))


def summarize_categories(items: list[SfxItem]) -> list[dict]:
    """Compact per-category digest for the chooser prompt (never the raw items)."""
    buckets: dict[str, dict] = {}
    for item in items:
        b = buckets.setdefault(item.category, {"category": item.category, "count": 0,
                                               "sample_descriptions": [], "tags": set()})
        b["count"] += 1
        if item.description and item.description not in b["sample_descriptions"] \
                and len(b["sample_descriptions"]) < _SUMMARY_SAMPLES:
            b["sample_descriptions"].append(item.description)
        b["tags"].update(item.tags)
    out = []
    for b in buckets.values():
        b["tags"] = sorted(b["tags"])
        out.append(b)
    return sorted(out, key=lambda b: b["category"])


def category_summary(profile) -> list[dict]:
    return summarize_categories(profile.items)


def identity_pool(identity_value: str) -> list[PoolEntry]:
    """All items from identity-pack profiles whose id matches identity_value."""
    pool: list[PoolEntry] = []
    for pack in list_packs():
        if pack.binding != "identity":
            continue
        for profile in pack.profiles:
            if profile.id == identity_value:
                pool.extend((pack.id, profile.id, it) for it in profile.items)
    return pool


def domain_pool(domain: str) -> list[PoolEntry]:
    """All global-pack items tagged with the given domain."""
    pool: list[PoolEntry] = []
    for pack in list_packs():
        if pack.binding != "global":
            continue
        for profile in pack.profiles:
            pool.extend((pack.id, profile.id, it) for it in profile.items if it.domain == domain)
    return pool


def weighted_choice(items: list[SfxItem], *, rng: Optional[random.Random] = None) -> Optional[SfxItem]:
    if not items:
        return None
    chooser = rng or random
    weights = [max(it.weight, 0.0) or 1.0 for it in items]
    return chooser.choices(items, weights=weights, k=1)[0]


def weighted_choice_entry(entries: list[PoolEntry], *,
                          rng: Optional[random.Random] = None) -> Optional[PoolEntry]:
    if not entries:
        return None
    chooser = rng or random
    weights = [max(it.weight, 0.0) or 1.0 for _, _, it in entries]
    return chooser.choices(entries, weights=weights, k=1)[0]


def items_in_category(profile, category: str) -> list[SfxItem]:
    return [it for it in profile.items if it.category == category]


def resolve_file_path(rel_path: str) -> Optional[Path]:
    """Resolve a manifest item path under SFX_ROOT, rejecting traversal."""
    root = SFX_ROOT.resolve()
    target = (SFX_ROOT / rel_path).resolve()
    if not str(target).startswith(str(root)):
        return None
    if not target.exists() or target.is_dir():
        return None
    return target
