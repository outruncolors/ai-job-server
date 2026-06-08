"""Migration's legacy-wildcard text rewrite: ``%%name%%`` → ``{{wc.name}}``.

Seeds ``%%``-bearing prompt text across every store's data shape (entries list,
content string, step graph, nested prompt-pal variables), runs the real migration
(stores redirected to tmp by the conftests), and asserts the canonical rewrite plus
idempotency on a second run.
"""

from __future__ import annotations

import json

import app.chain.context_library as context_store
import app.chain.sequences as sequence_store
import app.wildcards as wildcard_store
from app.cruddables import migrate
from app.prompt_pal import store as prompt_pal_store

_TS = "2026-01-01T00:00:00+00:00"


def _env(type_name, id, data, **extra):
    return {
        "schema_version": 1, "type": type_name, "id": id,
        "name": extra.get("name", id), "description": "", "tags": [],
        "created_at": _TS, "updated_at": _TS, "data": data,
    }


def _seed():
    wildcard_store._write_index([
        _env("wildcard", "scene", {"entries": [{"text": "draw %%color%%"}]}, name="Scene"),
    ])
    context_store._write_index([
        _env("context_item", "lore", {"content": "the realm of %%color%%"}, name="Lore"),
    ])
    sequence_store._write_index([
        _env("chain_sequence", "seq1", {"steps": [
            {"number": 1, "type": "llm", "alternatives": [
                {"prompt": "%%color%% scene", "voice_pre": "%%intro%%"}
            ]},
        ]}, name="Seq1"),
    ])
    path = prompt_pal_store.PROMPT_PAL_DIR / "pp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_env(
        "prompt_pal", "pp",
        {"app": "prattletale", "key": "k", "prompt": "say %%color%%",
         "variables": {"tone": "%%mood%%"}},
    )), encoding="utf-8")


def test_legacy_wildcards_rewritten_across_stores():
    _seed()
    report = migrate.run_migration()

    wc = wildcard_store.list_wildcards()[0]
    assert wc["data"]["entries"][0]["text"] == "draw {{wc.color}}"

    ctx = context_store.list_items()[0]
    assert ctx["data"]["content"] == "the realm of {{wc.color}}"

    seq = json.loads(sequence_store.INDEX_PATH.read_text())[0]
    alt = seq["data"]["steps"][0]["alternatives"][0]
    assert alt["prompt"] == "{{wc.color}} scene"
    assert alt["voice_pre"] == "{{wc.intro}}"

    pp = json.loads((prompt_pal_store.PROMPT_PAL_DIR / "pp.json").read_text())
    assert pp["data"]["prompt"] == "say {{wc.color}}"
    assert pp["data"]["variables"]["tone"] == "{{wc.mood}}"

    for t in ("wildcard", "context_item", "chain_sequence", "prompt_pal"):
        assert report["types"][t]["text_rewrites"] >= 1


def test_rewrite_is_idempotent():
    _seed()
    migrate.run_migration()
    report2 = migrate.run_migration()  # second pass: nothing left to rewrite
    for t in ("wildcard", "context_item", "chain_sequence", "prompt_pal"):
        assert report2["types"][t]["text_rewrites"] == 0
    # values unchanged after the second pass
    assert wildcard_store.list_wildcards()[0]["data"]["entries"][0]["text"] == "draw {{wc.color}}"


def test_dry_run_does_not_write():
    _seed()
    report = migrate.run_migration(dry_run=True)
    assert report["types"]["wildcard"]["text_rewrites"] >= 1  # counted
    # but disk is untouched — still the legacy spelling
    assert wildcard_store.list_wildcards()[0]["data"]["entries"][0]["text"] == "draw %%color%%"
