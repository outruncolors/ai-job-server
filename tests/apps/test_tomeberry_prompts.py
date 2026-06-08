"""Phase 3 — Tomeberry prompt library (base + 10 modes) + pack."""

from __future__ import annotations

from app.apps.tomeberry import prompts
from app.apps.tomeberry.models import MODES
from app.prompt_pal.registry import get_registered


def test_ten_modes_specced():
    assert set(prompts.MODE_SPECS) == set(MODES)
    assert len(prompts.MODE_SPECS) == 10
    assert set(prompts.MODE_PROMPTS) == set(prompts.MODE_SPECS)


def test_base_and_modes_registered():
    assert get_registered("tomeberry", "base") is not None
    for mode in prompts.MODE_SPECS:
        assert get_registered("tomeberry", f"mode.{mode}") is not None


def test_format_and_policy_text_cover_specs():
    for mode, spec in prompts.MODE_SPECS.items():
        assert spec["output_format"] in prompts.OUTPUT_FORMAT_TEXT, mode
        assert spec["change_policy"] in prompts.CHANGE_POLICY_TEXT, mode


def test_pack_builds():
    pack = prompts.build_pack()
    assert pack["id"] == "tomeberry_modes"
    assert len(pack["items"]) == 11  # base + 10
    assert all(it["type"] == "prompt_pal" for it in pack["items"])
    assert all(it["data"]["app"] == "tomeberry" for it in pack["items"])


def test_get_text_composes_with_vars():
    from app.prompt_pal.service import get_text

    vars_ = {k: "" for k in [
        "tale_title", "mode", "author_instruction", "saved_prompt", "active_pane",
        "current_structural_unit", "selected_text", "current_text", "premise",
        "project_context", "conversation_context", "request_context",
        "output_format", "change_policy",
    ]}
    vars_["author_instruction"] = "make it tense"
    txt = get_text("tomeberry", "mode.revise", variables=vars_)
    assert "make it tense" in txt
    # no leftover var tokens for keys we supplied
    assert "{{var.author_instruction}}" not in txt
