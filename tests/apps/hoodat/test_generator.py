from __future__ import annotations

import json

import pytest

from app.apps.hoodat import characters_store as cs
from app.apps.hoodat import generator
from app.chain.models import ChainLLMConfig

_VALID = {
    "name": "Ignored",  # user name should win
    "summary": "a tinkerer",
    "age": 41,
    "appearance": {
        "hair_color": "silver",
        "outfits": [{"name": "Work", "top": "lab coat", "primary": True}],
    },
    "personality": {"traits": ["curious"]},
    "experiences": [{"description": "first invention", "valence": "positive"}],
}


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )


def _fake_chain(write_map):
    """Return a fake execute_chain_job that writes the next queued output on each
    call. `write_map` is a list of strings written to final_output.txt in order;
    the last value repeats.
    """
    calls = {"n": 0}

    async def fake(job_id, job_dir, request, event_bus=None):
        i = min(calls["n"], len(write_map) - 1)
        calls["n"] += 1
        (job_dir / "final_output.txt").write_text(write_map[i], encoding="utf-8")
        # also drop an ideate prose file so the retry path has a seed
        ideate = job_dir / "steps" / "001_ideate"
        ideate.mkdir(parents=True, exist_ok=True)
        (ideate / "output.txt").write_text("prose notes", encoding="utf-8")

    return fake, calls


async def test_run_create_happy_path(monkeypatch):
    fake, calls = _fake_chain([json.dumps(_VALID)])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    character, job_id = await generator.run_create("Ada", "an inventor")
    assert character["name"] == "Ada"  # user name wins
    assert character["summary"] == "a tinkerer"
    assert character["appearance"]["outfits"][0]["top"] == "lab coat"
    assert character["experiences"] == [{"description": "first invention", "valence": "positive"}]
    assert job_id
    # persisted
    assert cs.get_character(character["id"])["age"] == 41
    assert calls["n"] == 1


async def test_run_create_retries_then_succeeds(monkeypatch):
    fake, calls = _fake_chain(["not json", "still bad", json.dumps(_VALID)])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    character, _ = await generator.run_create("Ada", "x")
    assert character["name"] == "Ada"
    assert calls["n"] == 3  # initial + 2 retries


async def test_run_create_gives_up_after_retries(monkeypatch):
    fake, _ = _fake_chain(["nope"])
    monkeypatch.setattr(generator, "execute_chain_job", fake)
    with pytest.raises(generator.GenerationError):
        await generator.run_create("Ada", "x")


async def test_run_create_requires_name():
    with pytest.raises(generator.GenerationError):
        await generator.run_create("  ", "x")


async def test_run_field_scalar(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(["  chestnut brown  \nextra line"])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, prompt_id, job_id = await generator.run_field(base["id"], "appearance", "hair_color")
    assert value == "chestnut brown"  # scalar = first trimmed line
    assert cs.get_character(base["id"])["appearance"]["hair_color"] == value
    assert job_id


async def test_run_field_nude_field_uses_existing_route(monkeypatch):
    # A flat nude field routes through the same per-field generate path.
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(["full and round"])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, _, _ = await generator.run_field(base["id"], "appearance", "breasts")
    assert value == "full and round"
    assert cs.get_character(base["id"])["appearance"]["breasts"] == value


async def test_run_field_list(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(["- brave\n- stubborn\n* witty"])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, _, _ = await generator.run_field(base["id"], "personality", "traits")
    assert value == ["brave", "stubborn", "witty"]
    assert cs.get_character(base["id"])["personality"]["traits"] == value


async def test_run_field_int(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(["She is about 37 years old."])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, _, _ = await generator.run_field(base["id"], "identity", "age")
    assert value == 37
    assert cs.get_character(base["id"])["age"] == 37


async def test_run_field_unknown_field():
    base = cs.create_character({"name": "Ada"})
    with pytest.raises(generator.GenerationError):
        await generator.run_field(base["id"], "nope", "nope")


def test_normalize_dialogue_strips_fences_and_quotes_keeps_newlines():
    assert generator._normalize_dialogue('```\n"Line one\nLine two"\n```') == "Line one\nLine two"
    assert generator._normalize_dialogue("  plain line  ") == "plain line"


async def test_run_dialogue_example_returns_value_without_persisting(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(['"Why, hello there!"'])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, prompt_id, job_id = await generator.run_dialogue_example(base["id"], ["a prior line"])
    assert value == "Why, hello there!"  # wrapping quotes stripped
    assert job_id
    # generation does NOT persist — the frontend owns the list
    assert cs.get_character(base["id"])["speaking_style"]["dialogue_examples"] == []


async def test_run_dialogue_example_missing_character(monkeypatch):
    fake, _ = _fake_chain(["x"])
    monkeypatch.setattr(generator, "execute_chain_job", fake)
    with pytest.raises(generator.GenerationError):
        await generator.run_dialogue_example("nope", [])


def _capturing_chain(output):
    """A fake execute_chain_job that records the request's steps and writes
    `output` to final_output.txt."""
    captured = {}

    async def fake(job_id, job_dir, request, event_bus=None):
        captured["steps"] = request.steps
        (job_dir / "final_output.txt").write_text(output, encoding="utf-8")

    return fake, captured


async def test_run_qa_answer_appends_guard_step(monkeypatch):
    base = cs.create_character({"name": "Ada", "speaking_style": {"description": "wry"}})
    fake, captured = _capturing_chain("Just words, no actions.")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, prompt_id, job_id = await generator.run_qa_answer(base["id"], "Who are you?", [])
    assert value == "Just words, no actions."
    assert job_id
    # qa.answer carries a spoken-only guard, so a SECOND "guard" step is appended.
    assert len(captured["steps"]) == 2
    assert captured["steps"][1].id == "guard"
    # generation does NOT persist — the frontend owns the qa list
    assert cs.get_character(base["id"])["qa"] == []


async def test_run_qa_answer_requires_question(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _capturing_chain("x")
    monkeypatch.setattr(generator, "execute_chain_job", fake)
    with pytest.raises(generator.GenerationError):
        await generator.run_qa_answer(base["id"], "   ", [])


async def test_run_qa_question_single_step(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, captured = _capturing_chain("What drives you?")
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, _, _ = await generator.run_qa_question(base["id"], [])
    assert value == "What drives you?"
    assert len(captured["steps"]) == 1  # no guard on the suggest-question prompt


async def test_run_dialogue_example_appends_guard_step(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, captured = _capturing_chain("A spoken line.")
    monkeypatch.setattr(generator, "execute_chain_job", fake)
    await generator.run_dialogue_example(base["id"], [])
    assert len(captured["steps"]) == 2  # dialogue.example is also guarded spoken-only
    assert captured["steps"][1].id == "guard"


def test_render_character_context_includes_qa():
    from app.apps.hoodat.prompts import render_character_context
    doc = cs.create_character({
        "name": "Ada",
        "qa": [{"question": "Who are you?", "answer": "An inventor."},
               {"question": "", "answer": "incomplete"}],
    })
    rendered = render_character_context(doc)
    assert "Q&A" in rendered
    assert "Q: Who are you?" in rendered and "A: An inventor." in rendered
    assert "incomplete" not in rendered  # incomplete pair dropped


def test_render_character_context_includes_dialogue_examples():
    from app.apps.hoodat.prompts import render_character_context
    doc = cs.create_character({
        "name": "Ada",
        "speaking_style": {"description": "wry", "dialogue_examples": ["Howdy, partner."]},
    })
    rendered = render_character_context(doc)
    assert "Dialogue examples:" in rendered
    assert "Howdy, partner." in rendered

    plain = render_character_context(cs.create_character({"name": "Bo"}))
    assert "Dialogue examples:" not in plain


def test_render_character_context_appearance_and_experiences():
    from app.apps.hoodat.prompts import render_character_context
    doc = cs.create_character({
        "name": "Ada",
        "appearance": {
            "hair_color": "silver", "hair_details": "in a bun",
            "breasts": "ample", "outfits": [{"name": "Work", "top": "lab coat", "primary": True}],
        },
        "experiences": [
            {"description": "won a prize", "valence": "positive"},
            {"description": "lost a friend", "valence": "negative"},
        ],
    })
    rendered = render_character_context(doc)
    assert "Hair: silver in a bun" in rendered            # combined color + details
    assert "Nude details:" in rendered and "ample" in rendered
    assert "Outfits:" in rendered and "lab coat" in rendered
    assert "Positive experiences:" in rendered and "won a prize" in rendered
    assert "Negative experiences:" in rendered and "lost a friend" in rendered


# ---- experiences -----------------------------------------------------------

def test_normalize_experience_valid_and_defaulting():
    assert generator._normalize_experience('{"description": "x", "valence": "negative"}') == {
        "description": "x", "valence": "negative"}
    # missing/unknown valence -> positive
    assert generator._normalize_experience('{"description": "y"}')["valence"] == "positive"
    assert generator._normalize_experience('{"description": "z", "valence": "??"}')["valence"] == "positive"
    with pytest.raises(generator.GenerationError):
        generator._normalize_experience("not json")
    with pytest.raises(generator.GenerationError):
        generator._normalize_experience('{"description": ""}')


async def test_run_experience_example_returns_value_without_persisting(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(['{"description": "Survived a shipwreck", "valence": "negative"}'])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, prompt_id, job_id = await generator.run_experience_example(base["id"], [])
    assert value == {"description": "Survived a shipwreck", "valence": "negative"}
    assert job_id
    # generation does NOT persist — the frontend owns the list
    assert cs.get_character(base["id"])["experiences"] == []


# ---- outfits ---------------------------------------------------------------

def test_normalize_outfit_drops_primary_and_fills_slots():
    out = generator._normalize_outfit('{"name": "Casual", "top": "tee", "primary": true}')
    assert out["name"] == "Casual" and out["top"] == "tee"
    assert "primary" not in out  # frontend owns the flag
    assert out["bottoms"] == "" and out["accessories"] == ""


async def test_run_outfit_returns_outfit_without_persisting(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(['{"name": "Beach", "top": "bikini", "bottoms": "shorts"}'])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, _, job_id = await generator.run_outfit(base["id"], [], {})
    assert value["name"] == "Beach" and value["top"] == "bikini"
    assert job_id
    assert cs.get_character(base["id"])["appearance"]["outfits"] == []


async def test_run_outfit_slot_scalar(monkeypatch):
    base = cs.create_character({"name": "Ada"})
    fake, _ = _fake_chain(["  worn leather boots  "])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, _, _ = await generator.run_outfit_slot(base["id"], "socks_shoes", {"top": "tee"}, [])
    assert value == "worn leather boots"


async def test_run_outfit_slot_unknown_slot():
    base = cs.create_character({"name": "Ada"})
    with pytest.raises(generator.GenerationError):
        await generator.run_outfit_slot(base["id"], "hat", {}, [])
