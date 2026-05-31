"""The one-time re-slug migration (`app.cruddables.migrate`).

Stores are redirected to tmp_path by the package conftest (index stores) and the
top-level conftest (prompt_pal / hoodat dirs), so these tests seed legacy docs straight
onto disk and run the real migration.
"""

from __future__ import annotations

import json

import app.chain.context_library as context_store
import app.chain.sequences as sequence_store
import app.wildcards as wildcard_store
from app.apps.hoodat import avatars as hoodat_avatars
from app.apps.hoodat import characters_store as hoodat_store
from app.cruddables import migrate
from app.prompt_pal import store as prompt_pal_store

UUID_A = "07bb113a-fd02-47ee-9a6b-310869df72a9"
UUID_B = "140ae1d2-42a7-4cc5-889c-45c54aa56a12"
UUID_CTX = "2158a0e6-8f80-4d75-bcee-9cd7ff6b76a2"
UUID_SEQ = "a76f20dc-47a3-45cb-967d-6684d19545fa"


def _write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# --- prompt_pal -------------------------------------------------------------

def test_prompt_pal_legacy_uuid_doc_is_reslugged_and_reshaped():
    _write_json(prompt_pal_store.PROMPT_PAL_DIR / f"{UUID_A}.json", {
        "id": UUID_A, "schema_version": 1,
        "app": "hoodat", "key": "field.personality.traits",
        "title": "Field — personality.traits", "description": "d", "tags": ["field"],
        "prompt": "body {{var.character}}", "variables": {},
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-02T00:00:00+00:00",
    })

    report = migrate.run_migration()

    new_id = "hoodat_field_personality_traits"
    assert report["types"]["prompt_pal"]["reslugged"] == 1
    assert report["types"]["prompt_pal"]["remap"] == {UUID_A: new_id}
    # old uuid file gone, new slug file present + envelope-shaped
    assert not (prompt_pal_store.PROMPT_PAL_DIR / f"{UUID_A}.json").exists()
    raw = json.loads((prompt_pal_store.PROMPT_PAL_DIR / f"{new_id}.json").read_text())
    assert raw["type"] == "prompt_pal" and raw["id"] == new_id
    assert raw["data"]["app"] == "hoodat"
    assert raw["data"]["prompt"] == "body {{var.character}}"
    assert raw["created_at"] == "2026-01-01T00:00:00+00:00"  # timestamps preserved
    # store sees it by logical (app, key)
    got = prompt_pal_store.get_by_app_key("hoodat", "field.personality.traits")
    assert got is not None and got["id"] == new_id


def test_prompt_pal_dedupes_by_app_key_keeping_newest():
    common = {"app": "hoodat", "key": "qa.answer", "title": "Q&A", "prompt": "p"}
    _write_json(prompt_pal_store.PROMPT_PAL_DIR / f"{UUID_A}.json", {
        "id": UUID_A, **common, "updated_at": "2026-01-01T00:00:00+00:00"})
    _write_json(prompt_pal_store.PROMPT_PAL_DIR / f"{UUID_B}.json", {
        "id": UUID_B, **common, "prompt": "newer", "updated_at": "2026-05-01T00:00:00+00:00"})

    report = migrate.run_migration()

    files = list(prompt_pal_store.PROMPT_PAL_DIR.glob("*.json"))
    assert len(files) == 1  # collapsed to one
    raw = json.loads(files[0].read_text())
    assert raw["id"] == "hoodat_qa_answer"
    assert raw["data"]["prompt"] == "newer"  # the newer doc won
    assert len(report["types"]["prompt_pal"]["dropped_duplicates"]) == 1


# --- hoodat avatars ---------------------------------------------------------

def test_hoodat_character_reslugged_with_avatar_rekey():
    _write_json(hoodat_store.CHARACTERS_DIR / f"{UUID_A}.json", {
        "id": UUID_A, "schema_version": 2,
        "name": "Dizzie Daylights", "summary": "artist",
        "avatar_path": f"/v1/apps/hoodat/characters/{UUID_A}/avatar",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    })
    hoodat_avatars.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    (hoodat_avatars.AVATARS_DIR / f"{UUID_A}.png").write_bytes(b"PNGDATA")

    report = migrate.run_migration()

    new_id = "dizzie_daylights"
    assert report["types"]["hoodat_character"]["remap"] == {UUID_A: new_id}
    assert report["avatar_renames"] == [{"old": UUID_A, "new": new_id, "file_renamed": True}]
    # avatar file moved
    assert not (hoodat_avatars.AVATARS_DIR / f"{UUID_A}.png").exists()
    assert (hoodat_avatars.AVATARS_DIR / f"{new_id}.png").read_bytes() == b"PNGDATA"
    # doc reslugged + avatar_path rewritten; flat-body API still works
    char = hoodat_store.get_character(new_id)
    assert char is not None
    assert char["avatar_path"] == f"/v1/apps/hoodat/characters/{new_id}/avatar"
    assert hoodat_store.get_character(UUID_A) is None


def test_hoodat_v1_appearance_doc_migrated_on_write():
    _write_json(hoodat_store.CHARACTERS_DIR / f"{UUID_B}.json", {
        "id": UUID_B, "schema_version": 1, "name": "Lolo Lorenz",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        "appearance": {"hair": "copper", "eyes": "dark", "primary_outfit": "coat"},
    })

    migrate.run_migration()

    raw = json.loads((hoodat_store.CHARACTERS_DIR / "lolo_lorenz.json").read_text())
    assert raw["type"] == "hoodat_character"
    # v1 Appearance fields upgraded to v2 by the store's read-normalization
    assert raw["data"]["appearance"]["hair_color"] == "copper"
    assert raw["data"]["content_version"] == 2


# --- chain-sequence reference fixing ---------------------------------------

def test_chain_sequence_references_are_remapped():
    context_store._write_index([
        {"id": UUID_CTX, "title": "My Context", "content": "hello"},
    ])
    sequence_store._write_index([
        {"id": UUID_SEQ, "name": "Target Seq", "steps": [], "variables": []},
        {"id": "11111111-2222-3333-4444-555555555555", "name": "Referrer",
         "steps": [
             {"number": 1, "alternatives": [
                 {"context_ids": [UUID_CTX], "sequence_id": UUID_SEQ}]},
             {"number": 2, "context_ids": [UUID_CTX]},  # v1 shorthand on the step
         ],
         "variables": []},
    ])

    migrate.run_migration()

    seqs = {s["name"]: s for s in sequence_store.list_sequences()}
    ref_steps = seqs["Referrer"]["data"]["steps"]
    assert ref_steps[0]["alternatives"][0]["context_ids"] == ["my_context"]
    assert ref_steps[0]["alternatives"][0]["sequence_id"] == "target_seq"
    assert ref_steps[1]["context_ids"] == ["my_context"]  # shorthand remapped too
    assert seqs["Target Seq"]["id"] == "target_seq"
    assert context_store.get_item("my_context") is not None


# --- idempotency / no-op ----------------------------------------------------

def test_idempotent_second_run_changes_nothing():
    _write_json(prompt_pal_store.PROMPT_PAL_DIR / f"{UUID_A}.json", {
        "id": UUID_A, "app": "hoodat", "key": "qa.answer", "title": "Q", "prompt": "p"})
    _write_json(hoodat_store.CHARACTERS_DIR / f"{UUID_B}.json", {
        "id": UUID_B, "schema_version": 2, "name": "Zed", "summary": "s",
        "avatar_path": f"/v1/apps/hoodat/characters/{UUID_B}/avatar"})
    (hoodat_avatars.AVATARS_DIR).mkdir(parents=True, exist_ok=True)
    (hoodat_avatars.AVATARS_DIR / f"{UUID_B}.png").write_bytes(b"X")

    migrate.run_migration()
    second = migrate.run_migration()

    assert second["types"]["prompt_pal"]["reslugged"] == 0
    assert second["types"]["hoodat_character"]["reslugged"] == 0
    assert second["types"]["hoodat_character"]["remap"] == {}
    assert second["avatar_renames"] == []


def test_already_slugged_envelope_doc_is_left_untouched():
    wildcard_store._write_index([{
        "schema_version": 1, "type": "wildcard", "id": "hair_colors",
        "name": "Hair Colors", "description": "", "tags": [],
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        "data": {"entries": [{"text": "blonde"}]},
    }])

    report = migrate.run_migration()

    assert report["types"]["wildcard"]["reslugged"] == 0
    assert wildcard_store.get_wildcard("hair_colors") is not None


def test_empty_stores_are_a_clean_noop():
    report = migrate.run_migration()
    for t in report["types"].values():
        assert t["total"] == 0 and t["reslugged"] == 0 and t["errors"] == []


# --- dry run ----------------------------------------------------------------

def test_dry_run_plans_without_writing():
    _write_json(prompt_pal_store.PROMPT_PAL_DIR / f"{UUID_A}.json", {
        "id": UUID_A, "app": "hoodat", "key": "qa.answer", "title": "Q", "prompt": "p"})

    report = migrate.run_migration(dry_run=True)

    assert report["dry_run"] is True
    assert report["types"]["prompt_pal"]["reslugged"] == 1
    # nothing written: the original uuid file is still there, no slug file
    assert (prompt_pal_store.PROMPT_PAL_DIR / f"{UUID_A}.json").exists()
    assert not (prompt_pal_store.PROMPT_PAL_DIR / "hoodat_qa_answer.json").exists()
