from __future__ import annotations

import pytest

from app.apps.blaboratory import prompts, prompts_store
from app.apps.blaboratory.prompt_compose import PromptCompositionError, compose


def test_literal_leaf():
    assert compose("just text") == "just text"


def test_one_level_var_substitution():
    node = {"prompt": "Hello {{var.who}}!", "variables": {"who": "world"}}
    assert compose(node) == "Hello world!"


def test_nested_prompt_piped_into_parent():
    node = {
        "prompt": "[A] {{var.inner}} [B]",
        "variables": {"inner": {"prompt": "deep {{var.x}}", "variables": {"x": "value"}}},
    }
    assert compose(node) == "[A] deep value [B]"


def test_stored_prompt_id_reference(monkeypatch):
    store = {"frag": {"prompt": "stored fragment"}}
    node = {"prompt": "<<{{var.f}}>>", "variables": {"f": {"prompt_id": "frag"}}}
    assert compose(node, store=lambda pid: store.get(pid)) == "<<stored fragment>>"


def test_missing_stored_prompt_raises():
    with pytest.raises(PromptCompositionError):
        compose({"prompt_id": "nope"}, store=lambda pid: None)


def test_prompt_id_without_store_raises():
    with pytest.raises(PromptCompositionError):
        compose({"prompt_id": "x"})


def test_cycle_over_depth_raises():
    # Self-referential stored prompt → blows the depth guard.
    store = {"loop": {"prompt": "{{var.again}}", "variables": {"again": {"prompt_id": "loop"}}}}
    with pytest.raises(PromptCompositionError):
        compose({"prompt_id": "loop"}, store=lambda pid: store.get(pid))


def test_chain_tokens_left_intact():
    # {{previous}} must survive composition for the chain executor to resolve later.
    node = {"prompt": "use {{previous}} and {{var.x}}", "variables": {"x": "X"}}
    assert compose(node) == "use {{previous}} and X"


def test_unresolved_var_left_intact():
    assert compose({"prompt": "keep {{var.missing}}"}) == "keep {{var.missing}}"


# ---- back-compat: get_prompt still yields the literal templates ----

def test_get_prompt_back_compat():
    assert prompts.get_prompt("ASSEMBLE") == prompts.ASSEMBLE
    assert "{{previous}}" in prompts.get_prompt("ASSEMBLE")


def test_get_prompt_reflects_prompt_pal_edit():
    """After seeding + editing the stored copy, get_prompt returns the edit."""
    from app.prompt_pal import registry, store as pp_store

    registry.seed_registered()
    entry = pp_store.get_by_app_key("blaboratory", "ASSEMBLE")
    assert entry is not None
    pp_store.update_entry(entry["id"], prompt="EDITED ASSEMBLE PROMPT")
    assert prompts.get_prompt("ASSEMBLE") == "EDITED ASSEMBLE PROMPT"
    assert prompts.get_prompt("IDEATE_FREE_TEXT") == prompts.IDEATE_FREE_TEXT


# ---- prompts_store roundtrip ----

def test_prompts_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts_store, "PROMPTS_DIR", tmp_path / "prompts")
    assert prompts_store.get_prompt_asset("x") is None
    node = {"prompt": "hi {{var.n}}", "variables": {"n": "there"}}
    prompts_store.save_prompt_asset("greet", node)
    assert prompts_store.get_prompt_asset("greet") == node
    assert "greet" in prompts_store.list_prompt_assets()
    # usable as a compose store
    assert compose({"prompt_id": "greet"}, store=prompts_store.get_prompt_asset) == "hi there"
