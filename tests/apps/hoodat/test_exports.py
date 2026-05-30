from __future__ import annotations

import pytest

from app.apps.hoodat import characters_store as cs
from app.apps.hoodat import exports, generator
from app.chain.models import ChainLLMConfig
from app.prompt_pal import store as pp_store


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )


def _make_export():
    return pp_store.create_entry({
        "app": "hoodat", "key": "export.bio", "title": "Bio",
        "prompt": "Detail={{var.detail}} char={{var.character}}", "variables": {},
    })


def test_list_exports_only_hoodat_exports():
    _make_export()
    pp_store.create_entry({"app": "hoodat", "key": "IDEATE", "title": "x", "prompt": "p"})
    pp_store.create_entry({"app": "other", "key": "export.z", "title": "y", "prompt": "p"})
    keys = {e["key"] for e in exports.list_exports()}
    assert keys == {"export.bio"}


async def test_run_export_composes_character_and_detail(monkeypatch):
    _make_export()
    char = cs.create_character({"name": "Ada", "occupation": "engineer"})

    captured = {}

    async def fake(job_id, job_dir, request, event_bus=None):
        captured["prompt"] = request.steps[0].alternatives[0].prompt
        (job_dir / "final_output.txt").write_text("EXPORTED", encoding="utf-8")

    monkeypatch.setattr(exports, "execute_chain_job", fake)
    text, job_id = await exports.run_export(char["id"], "export.bio", "detailed")
    assert text == "EXPORTED"
    assert job_id
    assert "Detail=detailed" in captured["prompt"]
    assert "Ada" in captured["prompt"]  # character rendered in


async def test_run_export_exposes_dialogue_examples(monkeypatch):
    pp_store.create_entry({
        "app": "hoodat", "key": "export.lines", "title": "Lines",
        "prompt": "Examples:\n{{var.dialogue_examples}}", "variables": {},
    })
    char = cs.create_character({
        "name": "Ada",
        "speaking_style": {"dialogue_examples": ["Eureka!", "To the lab."]},
    })

    captured = {}

    async def fake(job_id, job_dir, request, event_bus=None):
        captured["prompt"] = request.steps[0].alternatives[0].prompt
        (job_dir / "final_output.txt").write_text("OK", encoding="utf-8")

    monkeypatch.setattr(exports, "execute_chain_job", fake)
    await exports.run_export(char["id"], "export.lines", "standard")
    assert "- Eureka!" in captured["prompt"]
    assert "- To the lab." in captured["prompt"]


async def test_run_export_exposes_experiences(monkeypatch):
    pp_store.create_entry({
        "app": "hoodat", "key": "export.exp", "title": "Exp",
        "prompt": "Good:\n{{var.experiences_positive}}\nBad:\n{{var.experiences_negative}}",
        "variables": {},
    })
    char = cs.create_character({
        "name": "Ada",
        "experiences": [
            {"description": "won a prize", "valence": "positive"},
            {"description": "lost a friend", "valence": "negative"},
        ],
    })

    captured = {}

    async def fake(job_id, job_dir, request, event_bus=None):
        captured["prompt"] = request.steps[0].alternatives[0].prompt
        (job_dir / "final_output.txt").write_text("OK", encoding="utf-8")

    monkeypatch.setattr(exports, "execute_chain_job", fake)
    await exports.run_export(char["id"], "export.exp", "standard")
    assert "- won a prize" in captured["prompt"]
    assert "- lost a friend" in captured["prompt"]


async def test_run_export_bad_detail(monkeypatch):
    _make_export()
    char = cs.create_character({"name": "Ada"})
    with pytest.raises(generator.GenerationError):
        await exports.run_export(char["id"], "export.bio", "verbose")


async def test_run_export_missing_export():
    char = cs.create_character({"name": "Ada"})
    with pytest.raises(generator.GenerationError):
        await exports.run_export(char["id"], "export.nope", "standard")
