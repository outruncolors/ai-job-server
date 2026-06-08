"""The authoritative one-time **re-slug migration** for all cruddable types.

Every domain store *tolerates* legacy (pre-envelope) docs on read and uuid-keyed ids,
but the on-disk truth should be: envelope-shaped docs whose ``id`` is a human-readable
slug. This module performs that conversion in place, once:

1. **Reshape** every on-disk doc into the unified envelope shape (delegating to each
   store's own ``_normalize`` / ``_read_envelope`` so the result is byte-for-byte what
   the store would surface on read).
2. **Re-slug** any doc whose id is still a uuid: derive a human slug from its name (or,
   for prompt_pal, from ``app_key``), uniquified per type, and rename it.
3. **Fix references** that point at re-slugged ids — chain-sequence steps reference
   other sequences via ``sequence_id`` and context items via ``context_ids``.
4. **Re-key hoodat avatars** — rename ``config/hoodat/avatars/<old>.png`` → ``<new>.png``
   and rewrite the character's ``data.avatar_path`` URL.

Properties:

- **Idempotent** — a doc that is already envelope-shaped with a non-uuid id keeps its id
  untouched; a second run is a no-op (it only ever rewrites docs to the shape the store
  already returns on read). Re-runs after a partial crash are safe too: prompt_pal docs
  are de-duplicated by their logical ``(app, key)`` identity, so a leftover uuid copy
  collapses back into its slug copy rather than spawning a ``_2`` clone.
- **Per-item resilient** — a single malformed doc is recorded in the report and skipped
  rather than aborting the run.

Run it with ``.venv/bin/python -m app.cruddables.migrate`` (add ``--dry-run`` to preview).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app import image_prompts as image_prompt_store
from app import wildcards as wildcard_store
from app.apps.hoodat import avatars as hoodat_avatars
from app.apps.hoodat import characters_store as hoodat_store
from app.chain import context_library as context_store
from app.chain import sequences as sequence_store
from app.cruddables.envelope import slugify, unique_id
from app.prompt_pal import store as prompt_pal_store

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# Legacy wildcard syntax → the unified ``{{wc.name}}`` spelling. The resolver still
# READS ``%%name%%`` (see app.prompt_template), so this rewrite is cosmetic-but-
# canonical and idempotent: ``{{wc.x}}`` contains no ``%%`` so a second pass is a no-op.
_LEGACY_WC_RE = re.compile(r"%%([^%\n]+)%%")


def _rewrite_legacy_wc(text: str) -> str:
    return _LEGACY_WC_RE.sub(lambda m: "{{wc." + m.group(1).strip() + "}}", text)


def _deep_rewrite_strings(obj):
    """Rewrite ``%%name%%`` → ``{{wc.name}}`` in every string leaf of a JSON value.

    Returns ``(new_obj, count)``. Only string *values* change — dict keys (variable
    names, ids) and non-strings are untouched — so it is safe to run over a whole
    ``data`` blob regardless of type-specific shape (entries, content, step graphs,
    nested prompt nodes, character sheets).
    """
    if isinstance(obj, str):
        new = _rewrite_legacy_wc(obj)
        return new, (1 if new != obj else 0)
    if isinstance(obj, list):
        out, count = [], 0
        for v in obj:
            nv, c = _deep_rewrite_strings(v)
            out.append(nv)
            count += c
        return out, count
    if isinstance(obj, dict):
        out, count = {}, 0
        for k, v in obj.items():
            nv, c = _deep_rewrite_strings(v)
            out[k] = nv
            count += c
        return out, count
    return obj, 0

# Per-type slug fallback when a doc has no usable name (mirrors each store's own
# id-fallback so a nameless legacy doc gets the same base it would have on create).
_FALLBACK = {
    "wildcard": "wildcard",
    "context_item": "context",
    "image_prompt": "image_prompt",
    "chain_sequence": "sequence",
    "hoodat_character": "character",
    "prompt_pal": "prompt",
}


def _is_uuid(value: str | None) -> bool:
    return bool(value) and bool(_UUID_RE.match(value))


def _slug_base(env: dict, type_name: str) -> str:
    """Human-slug base for a fresh id, derived the same way the store would."""
    if type_name == "prompt_pal":
        data = env.get("data") or {}
        app = data.get("app") or prompt_pal_store.DEFAULT_APP
        key = data.get("key") or ""
        return slugify(f"{app}_{key}")
    name = env.get("name") or ""
    return slugify(name) if name.strip() else _FALLBACK[type_name]


# --- per-type storage drivers ----------------------------------------------

@dataclass
class _Driver:
    """How to read/normalize/write one cruddable type's on-disk docs.

    ``module`` attrs are resolved lazily (at call time) so tests can monkeypatch the
    storage dir / index path on the store module.
    """

    type_name: str
    storage: str  # "index" | "file"
    normalize: Callable[[dict], dict]

    # index storage
    read_index: Callable[[], list[dict]] | None = None
    write_index: Callable[[list[dict]], None] | None = None

    # file-per-doc storage
    dir_getter: Callable[[], Path] | None = None
    atomic_write: Callable[[Path, dict], None] | None = None

    def read_raw(self) -> list[dict]:
        if self.storage == "index":
            return [dict(d) for d in (self.read_index() or [])]  # type: ignore[misc]
        out: list[dict] = []
        directory = self.dir_getter()  # type: ignore[misc]
        if not directory.exists():
            return out
        for p in sorted(directory.glob("*.json")):
            out.append(json.loads(p.read_text(encoding="utf-8")))
        return out

    def write_all(self, finals: list[dict]) -> None:
        if self.storage == "index":
            self.write_index(finals)  # type: ignore[misc]
            return
        directory = self.dir_getter()  # type: ignore[misc]
        directory.mkdir(parents=True, exist_ok=True)
        keep: set[str] = set()
        for env in finals:
            self.atomic_write(directory / f"{env['id']}.json", env)  # type: ignore[misc]
            keep.add(env["id"])
        # Drop files no longer represented (e.g. the old uuid-named files we renamed).
        for p in directory.glob("*.json"):
            if p.stem not in keep:
                p.unlink()


def _drivers() -> list[_Driver]:
    return [
        _Driver("wildcard", "index", wildcard_store._normalize,
                read_index=wildcard_store._read_index,
                write_index=wildcard_store._write_index),
        _Driver("context_item", "index", context_store._normalize,
                read_index=context_store._read_index,
                write_index=context_store._write_index),
        _Driver("image_prompt", "index", image_prompt_store._normalize,
                read_index=image_prompt_store._read_index,
                write_index=image_prompt_store._write_index),
        _Driver("chain_sequence", "index", sequence_store._normalize,
                read_index=sequence_store._read_index,
                write_index=sequence_store._write_index),
        _Driver("prompt_pal", "file", prompt_pal_store._normalize,
                dir_getter=lambda: prompt_pal_store.PROMPT_PAL_DIR,
                atomic_write=prompt_pal_store._atomic_write),
        _Driver("hoodat_character", "file", hoodat_store._read_envelope,
                dir_getter=lambda: hoodat_store.CHARACTERS_DIR,
                atomic_write=hoodat_store._atomic_write),
    ]


# --- planning (pure: assign new ids, build remaps) -------------------------

@dataclass
class _TypePlan:
    type_name: str
    finals: list[dict] = field(default_factory=list)   # envelopes with final ids
    remap: dict[str, str] = field(default_factory=dict)  # old_id -> new_id (changed only)
    reslugged: int = 0
    text_rewrites: int = 0  # count of string leaves rewritten %% -> {{wc.}}
    dropped_duplicates: list[str] = field(default_factory=list)  # prompt_pal (app,key) dups
    errors: list[str] = field(default_factory=list)


def _dedupe_prompt_pal(envs: list[dict], plan: _TypePlan) -> list[dict]:
    """Collapse prompt_pal docs sharing ``(app, key)`` to one (the store's identity).

    Keeps the non-uuid / newest doc; records the dropped ids. Makes a re-run after a
    crashed migration safe (a leftover uuid copy folds back into its slug copy).
    """
    groups: dict[tuple, list[dict]] = {}
    for env in envs:
        d = env.get("data") or {}
        groups.setdefault((d.get("app"), d.get("key")), []).append(env)
    kept: list[dict] = []
    for members in groups.values():
        if len(members) == 1:
            kept.append(members[0])
            continue
        ordered = sorted(
            members,
            key=lambda e: (not _is_uuid(e.get("id")),
                           e.get("updated_at") or "", e.get("created_at") or ""),
        )
        winner = ordered[-1]
        kept.append(winner)
        for loser in ordered[:-1]:
            plan.dropped_duplicates.append(loser.get("id"))
    return kept


def _plan_type(driver: _Driver) -> _TypePlan:
    plan = _TypePlan(driver.type_name)
    envs: list[dict] = []
    for raw in driver.read_raw():
        try:
            envs.append(driver.normalize(dict(raw)))
        except Exception as exc:  # noqa: BLE001 — never abort the batch
            plan.errors.append(f"{raw.get('id')!r}: {exc}")
    if driver.type_name == "prompt_pal":
        envs = _dedupe_prompt_pal(envs, plan)

    # Rewrite legacy %%wildcard%% → {{wc.wildcard}} in every envelope's data blob.
    for env in envs:
        data = env.get("data")
        if isinstance(data, (dict, list)):
            new_data, c = _deep_rewrite_strings(data)
            if c:
                env["data"] = new_data
                plan.text_rewrites += c

    # Docs with a real (non-uuid) id keep it; reserve those ids first.
    kept = [e for e in envs if not _is_uuid(e.get("id"))]
    migrating = [e for e in envs if _is_uuid(e.get("id"))]
    taken = {e["id"] for e in kept}

    # Deterministic suffix assignment: oldest first, then by old id.
    for env in sorted(migrating, key=lambda e: (e.get("created_at") or "", e.get("id") or "")):
        old = env["id"]
        new = unique_id(_slug_base(env, driver.type_name), taken)
        taken.add(new)
        env["id"] = new
        if new != old:
            plan.remap[old] = new
            plan.reslugged += 1

    plan.finals = kept + migrating
    return plan


def _remap_node_refs(node: dict, seq_remap: dict[str, str], ctx_remap: dict[str, str]) -> None:
    """Rewrite ``sequence_id`` / ``context_ids`` on a step or alternative dict."""
    sid = node.get("sequence_id")
    if sid in seq_remap:
        node["sequence_id"] = seq_remap[sid]
    cids = node.get("context_ids")
    if isinstance(cids, list):
        node["context_ids"] = [ctx_remap.get(c, c) for c in cids]


def _apply_sequence_refs(plan: _TypePlan, seq_remap: dict[str, str], ctx_remap: dict[str, str]) -> None:
    """Fix cross-references inside every chain-sequence envelope's step graph."""
    if not seq_remap and not ctx_remap:
        return
    for env in plan.finals:
        steps = (env.get("data") or {}).get("steps") or []
        for step in steps:
            if not isinstance(step, dict):
                continue
            _remap_node_refs(step, seq_remap, ctx_remap)  # v1 shorthand on the step
            for alt in step.get("alternatives") or []:
                if isinstance(alt, dict):
                    _remap_node_refs(alt, seq_remap, ctx_remap)


def _apply_avatar_rekey(plan: _TypePlan, *, dry_run: bool) -> list[dict]:
    """Rename avatar files + rewrite ``avatar_path`` for re-slugged characters.

    Returns ``[{old, new, file_renamed}]`` for the report.
    """
    renames: list[dict] = []
    for env in plan.finals:
        new_id = env["id"]
        # Find the old id (the only key in remap mapping to this new id), if any.
        old_id = next((o for o, n in plan.remap.items() if n == new_id), None)
        if old_id is None:
            continue
        data = env.get("data") or {}
        if data.get("avatar_path"):
            data["avatar_path"] = hoodat_avatars._avatar_url(new_id)
            env["data"] = data
        old_file = hoodat_avatars._avatar_file(old_id)
        new_file = hoodat_avatars._avatar_file(new_id)
        renamed = False
        if old_file.exists() and old_file != new_file:
            if not dry_run:
                new_file.parent.mkdir(parents=True, exist_ok=True)
                old_file.replace(new_file)
            renamed = True
        renames.append({"old": old_id, "new": new_id, "file_renamed": renamed})
    return renames


# --- orchestration ---------------------------------------------------------

def run_migration(*, dry_run: bool = False) -> dict:
    """Run the full re-slug migration. Returns a report dict (no exceptions on bad docs)."""
    plans = {d.type_name: _plan_type(d) for d in _drivers()}

    # Fix chain-sequence references using the context-item + chain-sequence remaps.
    ctx_remap = plans["context_item"].remap
    seq_remap = plans["chain_sequence"].remap
    _apply_sequence_refs(plans["chain_sequence"], seq_remap, ctx_remap)

    # Re-key hoodat avatars (mutates avatar_path in the envelopes + renames files).
    avatar_renames = _apply_avatar_rekey(plans["hoodat_character"], dry_run=dry_run)

    if not dry_run:
        for driver in _drivers():
            driver.write_all(plans[driver.type_name].finals)

    return {
        "dry_run": dry_run,
        "types": {
            name: {
                "total": len(p.finals),
                "reslugged": p.reslugged,
                "text_rewrites": p.text_rewrites,
                "remap": dict(p.remap),
                "dropped_duplicates": list(p.dropped_duplicates),
                "errors": list(p.errors),
            }
            for name, p in plans.items()
        },
        "avatar_renames": avatar_renames,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="preview without writing")
    args = parser.parse_args()
    report = run_migration(dry_run=args.dry_run)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
