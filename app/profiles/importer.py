"""Apply a MasterProfile back onto live ai-job-server config.

`apply_master_profile(profile, mode=..., asset_source=...)` writes each domain's
embedded JSON back to its on-disk store and copies any referenced binary
assets (voice WAVs) into `config/voice_presets/`.

Mode:
  - "replace": each domain's index is wiped and rewritten from the profile.
  - "merge":   each domain is upserted by id; existing entries the profile
               does not mention are preserved. Single-blob domains (omnivoice
               config, comfyui config) are always overwritten — they have no
               natural id to merge on.

Robustness: every domain write goes through a tmp file + atomic rename, so a
mid-import failure leaves earlier domains durably applied and the failing
domain unchanged. The caller can re-run the import after fixing the cause.

Validation: wildcard and chain-sequence cycle checks run against the
post-merge state before each is written, so an import that would introduce a
cycle aborts that domain.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from .. import image_prompts as image_prompts_mod
from .. import voice_presets as voice_presets_mod
from .. import wildcards as wildcards_mod
from ..chain import context_library, sequences
from ..comfyui import config as comfyui_cfg
from ..llm_config import CONFIG_PATH as LLM_CONFIG_PATH, LLMConfigDoc, LLMPreset
from ..omnivoice import config as omnivoice_cfg
from .models import MasterProfile

Mode = Literal["replace", "merge"]


@dataclass
class ImportReport:
    mode: str
    domains: dict[str, int] = field(default_factory=dict)
    assets_copied: int = 0
    asset_warnings: list[str] = field(default_factory=list)


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _upsert_by_id(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {e["id"]: e for e in existing}
    for entry in incoming:
        by_id[entry["id"]] = entry
    return list(by_id.values())


def _read_index(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _final_index(path: Path, incoming: list[dict], mode: Mode) -> list[dict]:
    if mode == "replace":
        return list(incoming)
    return _upsert_by_id(_read_index(path), incoming)


# ---------- per-domain appliers ---------- #

def _apply_llm_config(profile: MasterProfile, mode: Mode) -> int:
    if mode == "replace":
        doc = profile.llm_config
    else:
        current = LLMConfigDoc()
        if LLM_CONFIG_PATH.exists():
            current = LLMConfigDoc.model_validate(
                json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
            )
        merged = _upsert_by_id(
            [p.model_dump() for p in current.presets],
            [p.model_dump() for p in profile.llm_config.presets],
        )
        doc = LLMConfigDoc(
            presets=[LLMPreset.model_validate(p) for p in merged],
            default_preset_id=profile.llm_config.default_preset_id
            or current.default_preset_id,
        )
    _atomic_write(LLM_CONFIG_PATH, doc.model_dump_json(indent=2))
    return len(doc.presets)


def _apply_omnivoice(profile: MasterProfile) -> int:
    _atomic_write(omnivoice_cfg.CONFIG_PATH, profile.omnivoice.model_dump_json(indent=2))
    omnivoice_cfg._config = None  # force reload on next get_config()
    return 1


def _apply_comfyui_config(profile: MasterProfile) -> int:
    _atomic_write(comfyui_cfg.CONFIG_PATH, profile.comfyui.model_dump_json(indent=2))
    comfyui_cfg._config = None
    return 1


def _apply_comfyui_workflows(profile: MasterProfile, mode: Mode) -> int:
    wf_dir = comfyui_cfg.WORKFLOWS_DIR
    wf_dir.mkdir(parents=True, exist_ok=True)
    if mode == "replace":
        for existing in wf_dir.glob("*.json"):
            existing.unlink()
    count = 0
    for filename, body in profile.comfyui_workflows.items():
        _atomic_write(wf_dir / filename, json.dumps(body, indent=2))
        count += 1
    return count


def _apply_wildcards(profile: MasterProfile, mode: Mode) -> int:
    incoming = [w.model_dump() for w in profile.wildcards]
    final = _final_index(wildcards_mod._INDEX_PATH, incoming, mode)
    for w in profile.wildcards:
        wildcards_mod.check_for_cycles(final, w.name)
    wildcards_mod._DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(wildcards_mod._INDEX_PATH, json.dumps(final, indent=2))
    return len(final)


def _apply_context_items(profile: MasterProfile, mode: Mode) -> int:
    incoming = [c.model_dump() for c in profile.context_items]
    final = _final_index(context_library.INDEX_PATH, incoming, mode)
    context_library.ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(context_library.INDEX_PATH, json.dumps(final, indent=2))
    return len(final)


def _apply_image_prompts(profile: MasterProfile, mode: Mode) -> int:
    incoming = [p.model_dump() for p in profile.image_prompts]
    final = _final_index(image_prompts_mod.INDEX_PATH, incoming, mode)
    image_prompts_mod.PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(image_prompts_mod.INDEX_PATH, json.dumps(final, indent=2))
    return len(final)


def _apply_chain_sequences(profile: MasterProfile, mode: Mode) -> int:
    incoming = [s.model_dump() for s in profile.chain_sequences]
    final = _final_index(sequences.INDEX_PATH, incoming, mode)
    for s in profile.chain_sequences:
        sequences.check_for_cycles(final, s.id)
    sequences.SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(sequences.INDEX_PATH, json.dumps(final, indent=2))
    return len(final)


def _apply_voice_presets(profile: MasterProfile, mode: Mode) -> int:
    incoming = [p.model_dump() for p in profile.voice_presets]
    final = _final_index(voice_presets_mod.INDEX_PATH, incoming, mode)
    voice_presets_mod.PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(voice_presets_mod.INDEX_PATH, json.dumps(final, indent=2))
    return len(final)


def _copy_assets(
    profile: MasterProfile,
    asset_source: Optional[Path],
    report: ImportReport,
) -> None:
    dest_dir = voice_presets_mod.PRESETS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    for asset in profile.asset_manifest:
        if asset.kind != "voice_wav":
            continue
        if asset_source is None:
            report.asset_warnings.append(
                f"no asset_source provided; cannot copy {asset.filename}"
            )
            continue
        src = asset_source / asset.filename
        if not src.exists():
            report.asset_warnings.append(
                f"referenced asset missing from source: {asset.filename}"
            )
            continue
        shutil.copyfile(src, dest_dir / asset.filename)
        report.assets_copied += 1


# ---------- public entry point ---------- #

def apply_master_profile(
    profile: MasterProfile,
    *,
    mode: Mode = "replace",
    asset_source: Optional[Path] = None,
) -> ImportReport:
    if mode not in ("replace", "merge"):
        raise ValueError(f"unknown mode: {mode!r}")
    report = ImportReport(mode=mode)

    report.domains["llm_config"] = _apply_llm_config(profile, mode)
    report.domains["omnivoice"] = _apply_omnivoice(profile)
    report.domains["comfyui"] = _apply_comfyui_config(profile)
    report.domains["comfyui_workflows"] = _apply_comfyui_workflows(profile, mode)
    report.domains["voice_presets"] = _apply_voice_presets(profile, mode)
    report.domains["wildcards"] = _apply_wildcards(profile, mode)
    report.domains["context_items"] = _apply_context_items(profile, mode)
    report.domains["image_prompts"] = _apply_image_prompts(profile, mode)
    report.domains["chain_sequences"] = _apply_chain_sequences(profile, mode)

    _copy_assets(profile, asset_source, report)
    return report
