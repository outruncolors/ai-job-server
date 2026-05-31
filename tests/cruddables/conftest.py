from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def patch_cruddable_stores(tmp_path, monkeypatch):
    """Redirect every in-scope cruddable store + the packs dirs to tmp_path."""
    import app.wildcards as wildcards
    wc_dir = tmp_path / "wildcards"
    monkeypatch.setattr(wildcards, "_DIR", wc_dir)
    monkeypatch.setattr(wildcards, "_INDEX_PATH", wc_dir / "index.json")

    import app.chain.context_library as context_library
    ctx_dir = tmp_path / "context_items"
    monkeypatch.setattr(context_library, "ITEMS_DIR", ctx_dir)
    monkeypatch.setattr(context_library, "INDEX_PATH", ctx_dir / "index.json")

    import app.image_prompts as image_prompts
    ip_dir = tmp_path / "image_prompts"
    monkeypatch.setattr(image_prompts, "PROMPTS_DIR", ip_dir)
    monkeypatch.setattr(image_prompts, "INDEX_PATH", ip_dir / "index.json")

    import app.chain.sequences as sequences
    seq_dir = tmp_path / "chain_sequences"
    monkeypatch.setattr(sequences, "SEQUENCES_DIR", seq_dir)
    monkeypatch.setattr(sequences, "INDEX_PATH", seq_dir / "index.json")

    return tmp_path
