"""Prattletale Dialogue Feel System: wildcard seeding, the pure render/merge
helpers (feel.py), per-turn roll resolution, prompt construction, and the
update-if-unmodified prompt migration. Stores are monkeypatched to tmp."""

from __future__ import annotations

import pytest

from app import wildcards
from app.apps.prattletale import feel, generator, prompts, seed
from app.apps.prattletale.seed import (
    CADENCE_WILDCARD_NAME,
    DIALOGUE_MOVE_WILDCARD_NAME,
    EMOTIONAL_SHADE_WILDCARD_NAME,
    seed_dialogue_feel_wildcards,
)
from app.chain.models import ChainLLMConfig
from app.prompt_pal import store as pp_store


@pytest.fixture(autouse=True)
def _tmp_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(wildcards, "_DIR", tmp_path / "wildcards")
    monkeypatch.setattr(wildcards, "_INDEX_PATH", tmp_path / "wildcards" / "index.json")
    monkeypatch.setattr(pp_store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")


# ---- helpers ---------------------------------------------------------------

def _char(**voice_feel) -> dict:
    return {"name": "Mara", "speaking_style": {"voice_feel": voice_feel}} if voice_feel \
        else {"name": "Mara", "speaking_style": {}}


def _conv(*, enabled=True, roll=True, **override) -> dict:
    return {"config": {"dialogue_feel_enabled": enabled,
                       "dialogue_feel_roll_enabled": roll,
                       "dialogue_feel": override}}


# ---- seeding ---------------------------------------------------------------

def test_seed_creates_all_three_feel_wildcards():
    created = seed_dialogue_feel_wildcards()
    assert created == 3
    names = {w["name"] for w in wildcards.list_wildcards()}
    assert {DIALOGUE_MOVE_WILDCARD_NAME, EMOTIONAL_SHADE_WILDCARD_NAME,
            CADENCE_WILDCARD_NAME} <= names


def test_seed_feel_is_idempotent_and_does_not_clobber():
    seed_dialogue_feel_wildcards()
    wid = next(w["id"] for w in wildcards.list_wildcards()
               if w["name"] == DIALOGUE_MOVE_WILDCARD_NAME)
    wildcards.update_wildcard(wid, DIALOGUE_MOVE_WILDCARD_NAME, [{"text": "edited", "weight": 1}])

    assert seed_dialogue_feel_wildcards() == 0  # all present -> nothing created
    matching = [w for w in wildcards.list_wildcards() if w["name"] == DIALOGUE_MOVE_WILDCARD_NAME]
    assert len(matching) == 1
    assert matching[0]["data"]["entries"] == [{"text": "edited", "weight": 1}]


# ---- render_voice_feel (merge) ---------------------------------------------

def test_voice_feel_empty_renders_nothing():
    assert feel.render_voice_feel(_char(), _conv()) == ""


def test_voice_feel_renders_only_nonempty_fields():
    block = feel.render_voice_feel(
        _char(enabled=True, cadence="clipped, dry", avoid="therapist voice"), _conv())
    assert "VOICE FEEL PROFILE" in block
    assert "Cadence: clipped, dry" in block
    assert "Avoid: therapist voice" in block
    assert "Lexicon" not in block  # empty field omitted -> no dangling label


def test_voice_feel_override_beats_character():
    char = _char(enabled=True, cadence="base cadence")
    block = feel.render_voice_feel(char, _conv(cadence="override cadence"))
    assert "Cadence: override cadence" in block
    assert "base cadence" not in block


def test_voice_feel_character_disabled_drops_character_fields():
    char = _char(enabled=False, cadence="hidden")
    assert feel.render_voice_feel(char, _conv()) == ""
    # ...but a conversation override still applies
    assert "Cadence: kept" in feel.render_voice_feel(char, _conv(cadence="kept"))


def test_voice_feel_master_gate_off_renders_nothing():
    char = _char(enabled=True, cadence="x")
    assert feel.render_voice_feel(char, _conv(enabled=False)) == ""


# ---- render_voice_examples -------------------------------------------------

def test_voice_examples_from_character():
    char = _char(enabled=True, examples=["[say] no.", "[say] fine."])
    block = feel.render_voice_examples(char, _conv())
    assert "RECENT GOOD VOICE EXAMPLES" in block and "[say] no." in block


def test_voice_examples_override_replaces_character():
    char = _char(enabled=True, examples=["base"])
    block = feel.render_voice_examples(char, _conv(examples=["override one"]))
    assert "override one" in block and "base" not in block


def test_voice_examples_capped_at_six():
    char = _char(enabled=True, examples=[f"line {i}" for i in range(8)])
    block = feel.render_voice_examples(char, _conv())
    assert block.count("line ") == 6


def test_voice_examples_empty_renders_nothing():
    assert feel.render_voice_examples(_char(), _conv()) == ""


# ---- resolve_dialogue_feel_roll --------------------------------------------

def test_roll_disabled_is_empty():
    seed_dialogue_feel_wildcards()
    assert feel.resolve_dialogue_feel_roll("mara", enabled=False) == ""


def test_roll_uses_globals_when_no_character_override():
    seed_dialogue_feel_wildcards()
    block = feel.resolve_dialogue_feel_roll("mara")
    assert "THIS TURN'S DIALOGUE FEEL" in block
    assert "Emotional shade:" in block and "Move:" in block and "Cadence:" in block


def test_roll_prefers_character_specific_wildcard():
    seed_dialogue_feel_wildcards()
    # single deterministic entry on a character-specific shade wildcard
    wildcards.create_wildcard(f"{EMOTIONAL_SHADE_WILDCARD_NAME}:mara",
                              [{"text": "MARA-ONLY-SHADE", "weight": 1}])
    block = feel.resolve_dialogue_feel_roll("mara")
    assert "Emotional shade: MARA-ONLY-SHADE" in block
    # the other categories still resolve from the globals
    assert "Move:" in block and "Cadence:" in block


def test_roll_empty_when_wildcards_absent():
    assert feel.resolve_dialogue_feel_roll("mara") == ""


# ---- prompt construction ---------------------------------------------------

def _ctx() -> dict:
    return {"character": "c", "scenario": "s", "role_instructions": "r",
            "user_persona": "p", "transcript": "[User] hi",
            "voice_feel": "VOICE-FEEL-SENTINEL", "voice_examples": ""}


def test_turn_prompt_default_carries_feel_tokens():
    raw = generator.get_text("prattletale", "turn", variables={})
    # the in-code default has the splice points (vars unresolved here)
    assert "{{var.voice_feel}}" in raw or "VOICE-FEEL" in prompts.TURN
    assert "{{var.dialogue_feel_roll}}" in prompts.TURN
    assert "STYLE FLOOR" in prompts.TURN


def test_build_turn_request_resolves_roll_into_turn_and_variety():
    seed_dialogue_feel_wildcards()
    seed.seed_message_style_wildcard()
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"),
        variety=True, counterpart_id="mara")
    turn_prompt = req.steps[0].alternatives[0].prompt
    # the per-turn roll is resolved (not a raw token), and the stable profile var
    # passed through context_vars is substituted too
    assert "THIS TURN'S DIALOGUE FEEL" in turn_prompt
    assert "{{var.dialogue_feel_roll}}" not in turn_prompt
    assert "VOICE-FEEL-SENTINEL" in turn_prompt

    variety_step = next(s for s in req.steps if s.id == "variety")
    vp = variety_step.alternatives[0].prompt
    assert "THIS TURN'S DIALOGUE FEEL" in vp  # same roll reaches the editor
    assert "VOICE-FEEL-SENTINEL" in vp


def test_build_turn_request_roll_disabled_leaves_no_roll_block():
    seed_dialogue_feel_wildcards()
    seed.seed_message_style_wildcard()
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"),
        dialogue_feel_roll_enabled=False, counterpart_id="mara")
    turn_prompt = req.steps[0].alternatives[0].prompt
    assert "THIS TURN'S DIALOGUE FEEL" not in turn_prompt
    assert "{{var.dialogue_feel_roll}}" not in turn_prompt  # empty var -> blank, not literal


# ---- migration (update-if-unmodified) --------------------------------------

def _store_prompt(key: str, text: str) -> None:
    pp_store.create_entry({"app": "prattletale", "key": key, "title": key, "prompt": text})


def test_migration_updates_unmodified_stored_prompt():
    _store_prompt("turn", prompts._LEGACY_TURN_V1)
    _store_prompt("variety", prompts._LEGACY_VARIETY_V1)
    updated = prompts.migrate_turn_variety_prompts()
    assert set(updated) == {"turn", "variety"}
    assert pp_store.get_by_app_key("prattletale", "turn")["data"]["prompt"] == prompts.TURN
    assert pp_store.get_by_app_key("prattletale", "variety")["data"]["prompt"] == prompts.VARIETY


def test_migration_leaves_edited_prompt_untouched():
    _store_prompt("turn", "MY EDITED TURN PROMPT")
    updated = prompts.migrate_turn_variety_prompts()
    assert "turn" not in updated
    assert pp_store.get_by_app_key("prattletale", "turn")["data"]["prompt"] == "MY EDITED TURN PROMPT"


def test_migration_noop_when_absent():
    assert prompts.migrate_turn_variety_prompts() == []


# ---- feel director (context-aware roll) ------------------------------------

def test_parse_director_roll_extracts_and_orders():
    raw = ("Sure! Here you go:\n"
           "Move: deflect, then admit one thing\n"
           "Emotional shade: guarded but curious\n"
           "Cadence: clipped, one beat\n"
           "(that's my pick)")
    block = feel.parse_director_roll(raw)
    # preamble/extra dropped; canonical order shade -> move -> cadence
    assert block == (
        "THIS TURN'S DIALOGUE FEEL — obey without mentioning it:\n"
        "<dialogue_feel_roll>\n"
        "Emotional shade: guarded but curious\n"
        "Move: deflect, then admit one thing\n"
        "Cadence: clipped, one beat\n"
        "</dialogue_feel_roll>"
    )


def test_parse_director_roll_empty_when_unusable():
    assert feel.parse_director_roll("no labels here, just prose") == ""
    assert feel.parse_director_roll("") == ""


def test_build_turn_request_uses_director_override_verbatim():
    # an explicit roll override is used as-is (no wildcard draw needed)
    override = feel.parse_director_roll("Emotional shade: cold\nMove: end it\nCadence: flat")
    req = generator.build_turn_request(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"),
        dialogue_feel_roll=override, counterpart_id="mara")
    tp = req.steps[0].alternatives[0].prompt
    assert "Emotional shade: cold" in tp and "Move: end it" in tp


async def test_director_roll_runs_one_step_job_and_parses(monkeypatch):
    # stub the LLM: the director job writes three labeled lines
    async def fake(job_id, job_dir, request, event_bus=None):
        assert request.steps[0].id == "feel_director"
        (job_dir / "final_output.txt").write_text(
            "Emotional shade: wary\nMove: ask one sharp question\nCadence: short",
            encoding="utf-8")
    monkeypatch.setattr(generator, "execute_chain_job", fake)
    block = await generator.direct_feel_roll(
        _ctx(), ChainLLMConfig(api_base="http://x", model="m"), counterpart_id="mara")
    assert "Emotional shade: wary" in block and "Move: ask one sharp question" in block


# ---- build_context wires the stable blocks ---------------------------------

def test_build_context_includes_voice_feel_and_examples():
    char = _char(enabled=True, cadence="clipped", examples=["[say] no."])
    conv = _conv()
    ctx = generator.build_context(conv, char, {"turns": []})
    assert "voice_feel" in ctx and "Cadence: clipped" in ctx["voice_feel"]
    assert "voice_examples" in ctx and "[say] no." in ctx["voice_examples"]
