"""Compose tests against the shared module. The blaboratory re-export shim is
covered by tests/apps/test_prompt_compose.py; this asserts the shared import path.
"""

from __future__ import annotations

import pytest

from app.prompt_pal.compose import PromptCompositionError, compose


def test_literal_leaf():
    assert compose("just text") == "just text"


def test_var_substitution_and_nesting():
    node = {
        "prompt": "[A] {{var.inner}} [B]",
        "variables": {"inner": {"prompt": "deep {{var.x}}", "variables": {"x": "value"}}},
    }
    assert compose(node) == "[A] deep value [B]"


def test_chain_tokens_and_unresolved_vars_left_intact():
    node = {"prompt": "use {{previous}} and {{var.missing}}"}
    assert compose(node) == "use {{previous}} and {{var.missing}}"


def test_stored_prompt_id_reference():
    db = {"frag": {"prompt": "stored fragment"}}
    node = {"prompt": "<<{{var.f}}>>", "variables": {"f": {"prompt_id": "frag"}}}
    assert compose(node, store=lambda pid: db.get(pid)) == "<<stored fragment>>"


def test_cycle_raises():
    db = {"loop": {"prompt": "{{var.a}}", "variables": {"a": {"prompt_id": "loop"}}}}
    with pytest.raises(PromptCompositionError):
        compose({"prompt_id": "loop"}, store=lambda pid: db.get(pid))


def test_shim_reexports_same_object():
    from app.apps.blaboratory.prompt_compose import compose as shim_compose

    assert shim_compose is compose
