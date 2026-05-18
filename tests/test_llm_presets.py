from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------

def test_llm_preset_schema_defaults():
    from app.llm.models import LLMPreset

    p = LLMPreset(name="gemma-3", model_path="/m.gguf")
    assert p.capabilities == ["text"]
    assert p.args == {}
    assert p.description is None
    assert p.to_manager_dict() == {"model_path": "/m.gguf", "args": {}}


def test_llm_preset_name_must_be_kebab_case():
    from app.llm.models import LLMPreset
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LLMPreset(name="Gemma 3", model_path="/m.gguf")
    with pytest.raises(ValidationError):
        LLMPreset(name="gemma_3", model_path="/m.gguf")
    LLMPreset(name="gemma-3-27b-highctx", model_path="/m.gguf")


def test_llm_preset_capabilities_validated():
    from app.llm.models import LLMPreset
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LLMPreset(name="x", model_path="/m.gguf", capabilities=[])
    with pytest.raises(ValidationError):
        LLMPreset(name="x", model_path="/m.gguf", capabilities=["audio"])
    with pytest.raises(ValidationError):
        # "text" must be present
        LLMPreset(name="x", model_path="/m.gguf", capabilities=["vision"])
    LLMPreset(name="x", model_path="/m.gguf", capabilities=["text", "vision"])


# ---------------------------------------------------------------------------
# CRUD module
# ---------------------------------------------------------------------------

def test_llm_presets_roundtrip(tmp_path, monkeypatch):
    import app.llm_presets as lp
    from app.llm.models import LLMPreset

    monkeypatch.setattr(lp, "PRESETS_DIR", tmp_path / "llm_presets")

    assert lp.list_presets() == []
    assert lp.get_preset("nope") is None

    preset = LLMPreset(
        name="gemma-3-27b-highctx",
        model_path="/opt/models/gemma.gguf",
        args={"ctx_size": 32768, "flash_attn": True, "mmproj": None},
        capabilities=["text"],
        description="High ctx",
    )
    saved = lp.save_preset(preset)
    assert saved["name"] == "gemma-3-27b-highctx"
    # File written
    on_disk = json.loads(
        (tmp_path / "llm_presets" / "gemma-3-27b-highctx.json").read_text()
    )
    assert on_disk["model_path"] == "/opt/models/gemma.gguf"
    assert on_disk["args"]["mmproj"] is None  # preserves null fields

    fetched = lp.get_preset("gemma-3-27b-highctx")
    assert fetched["args"]["ctx_size"] == 32768
    assert fetched["description"] == "High ctx"

    listed = lp.list_presets()
    assert len(listed) == 1
    assert listed[0]["name"] == "gemma-3-27b-highctx"

    assert lp.delete_preset("gemma-3-27b-highctx") is True
    assert lp.delete_preset("gemma-3-27b-highctx") is False
    assert lp.list_presets() == []


def test_llm_presets_invalid_name_safe(tmp_path, monkeypatch):
    import app.llm_presets as lp

    monkeypatch.setattr(lp, "PRESETS_DIR", tmp_path / "llm_presets")
    # Path-traversal / invalid names short-circuit safely.
    assert lp.get_preset("../etc/passwd") is None
    assert lp.delete_preset("../etc/passwd") is False


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------

def _body(name="gemma-3", **overrides):
    body = {
        "name": name,
        "model_path": "/m.gguf",
        "args": {"ctx_size": 4096},
        "capabilities": ["text"],
    }
    body.update(overrides)
    return body


def test_list_empty(client):
    r = client.get("/v1/llm-presets")
    assert r.status_code == 200
    assert r.json() == {"presets": []}


def test_create_get_update_delete_flow(client):
    r = client.post("/v1/llm-presets", json=_body())
    assert r.status_code == 201
    assert r.json()["name"] == "gemma-3"

    r = client.get("/v1/llm-presets/gemma-3")
    assert r.status_code == 200
    assert r.json()["args"] == {"ctx_size": 4096}

    r = client.get("/v1/llm-presets")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()["presets"]] == ["gemma-3"]

    # Update — args + capabilities
    updated = _body(args={"ctx_size": 8192, "flash_attn": True}, capabilities=["text", "vision"])
    r = client.put("/v1/llm-presets/gemma-3", json=updated)
    assert r.status_code == 200
    assert r.json()["args"] == {"ctx_size": 8192, "flash_attn": True}
    assert r.json()["capabilities"] == ["text", "vision"]

    r = client.delete("/v1/llm-presets/gemma-3")
    assert r.status_code == 200

    r = client.get("/v1/llm-presets/gemma-3")
    assert r.status_code == 404


def test_create_duplicate_returns_409(client):
    r = client.post("/v1/llm-presets", json=_body())
    assert r.status_code == 201
    r = client.post("/v1/llm-presets", json=_body())
    assert r.status_code == 409


def test_create_invalid_name_returns_422(client):
    r = client.post("/v1/llm-presets", json=_body(name="Bad Name"))
    assert r.status_code == 422


def test_update_missing_returns_404(client):
    r = client.put("/v1/llm-presets/nope", json=_body(name="nope"))
    assert r.status_code == 404


def test_delete_missing_returns_404(client):
    r = client.delete("/v1/llm-presets/nope")
    assert r.status_code == 404


def test_llm_endpoints_renamed_route_works(client, tmp_path, monkeypatch):
    """Sanity: /v1/llm-endpoints (formerly /v1/llm-presets) still serves the
    OpenAI-compatible endpoint config store."""
    import app.llm_config as cfg
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "llm_config.json")

    r = client.get("/v1/llm-endpoints")
    assert r.status_code == 200
    assert r.json() == {"presets": [], "default_preset_id": None}

    r = client.post("/v1/llm-endpoints", json={
        "name": "local",
        "api_base": "http://127.0.0.1:8080/v1",
        "model": "gemma-3",
    })
    assert r.status_code == 200
    eid = r.json()["id"]

    r = client.delete(f"/v1/llm-endpoints/{eid}")
    assert r.status_code == 200


def test_old_llm_presets_route_no_longer_returns_endpoint_shape(client):
    """The /v1/llm-presets URL now serves the llama.cpp preset shape,
    not the legacy {presets:[], default_preset_id} shape."""
    r = client.get("/v1/llm-presets")
    assert r.status_code == 200
    body = r.json()
    assert "default_preset_id" not in body
    assert body == {"presets": []}
