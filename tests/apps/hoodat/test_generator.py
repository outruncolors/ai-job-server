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
    "appearance": {"hair": "silver", "primary_outfit": "lab coat"},
    "personality": {"traits": ["curious"]},
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
    assert character["appearance"]["primary_outfit"] == "lab coat"
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
    fake, _ = _fake_chain(["  a battered tweed jacket  \nextra line"])
    monkeypatch.setattr(generator, "execute_chain_job", fake)

    value, prompt_id, job_id = await generator.run_field(base["id"], "appearance", "primary_outfit")
    assert value == "a battered tweed jacket"  # scalar = first trimmed line
    assert cs.get_character(base["id"])["appearance"]["primary_outfit"] == value
    assert job_id


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
