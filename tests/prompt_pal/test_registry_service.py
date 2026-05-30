from __future__ import annotations

import pytest

from app.prompt_pal import registry, service, store


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROMPT_PAL_DIR", tmp_path / "prompt_pal")


def test_get_text_falls_back_to_registered_default():
    registry.register("testapp", "GREET", title="Greet", prompt="hello {{var.who}}", variables={"who": "world"})
    # No store file yet -> in-code default, composed.
    assert service.get_text("testapp", "GREET") == "hello world"


def test_seed_is_idempotent_and_absent_only():
    registry.register("testapp", "SEEDME", title="Seed", prompt="seeded body")
    registry.seed_registered()
    first = store.get_by_app_key("testapp", "SEEDME")
    assert first is not None

    # Edit the stored copy, then re-seed: the edit must survive.
    store.update_entry(first["id"], prompt="EDITED")
    registry.seed_registered()
    again = store.get_by_app_key("testapp", "SEEDME")
    assert again["id"] == first["id"]
    assert again["prompt"] == "EDITED"


def test_store_copy_wins_over_default():
    registry.register("testapp", "WIN", title="Win", prompt="default body")
    registry.seed_registered()
    entry = store.get_by_app_key("testapp", "WIN")
    store.update_entry(entry["id"], prompt="edited body {{var.z}}", variables={"z": "Z"})
    assert service.get_text("testapp", "WIN") == "edited body Z"


def test_get_text_runtime_variable_overlay():
    registry.register("testapp", "TPL", title="Tpl", prompt="char={{var.character}}")
    assert service.get_text("testapp", "TPL", variables={"character": "Bob"}) == "char=Bob"


def test_id_for():
    registry.register("testapp", "IDQ", title="IdQ", prompt="x")
    assert service.id_for("testapp", "IDQ") is None  # not seeded
    registry.seed_registered()
    assert service.id_for("testapp", "IDQ") == store.get_by_app_key("testapp", "IDQ")["id"]


def test_get_text_unknown_raises():
    with pytest.raises(service.UnknownPromptError):
        service.get_text("nosuchapp", "nosuchkey")
