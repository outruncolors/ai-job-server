from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.apps.hoodat import characters_store as cs
from app.apps.hoodat import generator
from app.chain.models import ChainLLMConfig
from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stub_generation(monkeypatch):
    monkeypatch.setattr(
        generator, "get_default_as_chain_llm_config",
        lambda: ChainLLMConfig(api_base="http://x", model="m"),
    )

    async def fake(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text(
            json.dumps({"name": "X", "summary": "s", "age": 30}), encoding="utf-8"
        )

    monkeypatch.setattr(generator, "execute_chain_job", fake)


def test_create_get_list(client):
    r = client.post("/v1/apps/hoodat/characters", json={"name": "Ada", "prompt": "inventor"})
    assert r.status_code == 201
    char = r.json()["character"]
    assert char["name"] == "Ada"

    assert client.get(f"/v1/apps/hoodat/characters/{char['id']}").status_code == 200
    listed = client.get("/v1/apps/hoodat/characters").json()["characters"]
    assert any(c["id"] == char["id"] for c in listed)
    assert "summary" in listed[0]  # summary view


def test_create_requires_name(client):
    assert client.post("/v1/apps/hoodat/characters", json={"name": "  "}).status_code == 422


def test_get_missing_404(client):
    assert client.get("/v1/apps/hoodat/characters/nope").status_code == 404


def test_update_and_protected_keys(client):
    char = cs.create_character({"name": "Ada"})
    r = client.put(
        f"/v1/apps/hoodat/characters/{char['id']}",
        json={"tagline": "the analyst", "appearance": {"hair": "red"}, "id": "evil"},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["tagline"] == "the analyst"
    assert updated["appearance"]["hair"] == "red"
    assert updated["id"] == char["id"]  # id not overwritten


def test_update_missing_404(client):
    assert client.put("/v1/apps/hoodat/characters/nope", json={"tagline": "x"}).status_code == 404


def test_delete(client):
    char = cs.create_character({"name": "Ada"})
    assert client.delete(f"/v1/apps/hoodat/characters/{char['id']}").status_code == 200
    assert client.delete(f"/v1/apps/hoodat/characters/{char['id']}").status_code == 404


def test_generate_field(client, monkeypatch):
    char = cs.create_character({"name": "Ada"})

    async def fake_field(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text("a tweed jacket", encoding="utf-8")

    monkeypatch.setattr(generator, "execute_chain_job", fake_field)
    r = client.post(f"/v1/apps/hoodat/characters/{char['id']}/fields/appearance/primary_outfit/generate")
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "a tweed jacket"
    assert "prompt_id" in body and "job_id" in body


def test_generate_dialogue_example(client, monkeypatch):
    char = cs.create_character({"name": "Ada"})

    async def fake_dlg(job_id, job_dir, request, event_bus=None):
        (job_dir / "final_output.txt").write_text("A wry little quip.", encoding="utf-8")

    monkeypatch.setattr(generator, "execute_chain_job", fake_dlg)
    r = client.post(
        f"/v1/apps/hoodat/characters/{char['id']}/dialogue-examples/generate",
        json={"examples": ["a prior line"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "A wry little quip."
    assert "prompt_id" in body and "job_id" in body
    # generation does not persist; the list is unchanged server-side
    assert cs.get_character(char["id"])["speaking_style"]["dialogue_examples"] == []


def test_update_persists_dialogue_examples(client):
    char = cs.create_character({"name": "Ada"})
    r = client.put(
        f"/v1/apps/hoodat/characters/{char['id']}",
        json={"speaking_style": {"dialogue_examples": ["Howdy."]}},
    )
    assert r.status_code == 200
    assert r.json()["speaking_style"]["dialogue_examples"] == ["Howdy."]


def test_avatar_generate_503_without_image_capability(client, tmp_path, monkeypatch):
    char = cs.create_character({"name": "Ada"})
    # Write a server.json that excludes the image capability, reset cache.
    import app.server as s
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "server.json").write_text(
        json.dumps({"capabilities": ["web", "llm"], "peers": []}), encoding="utf-8"
    )
    s.reset_server_config()
    r = client.post(f"/v1/apps/hoodat/characters/{char['id']}/avatar/generate")
    assert r.status_code == 503
    assert r.json()["detail"]["needed"] == "image"


def test_avatar_upload_and_serve(client):
    char = cs.create_character({"name": "Ada"})
    files = {"file": ("a.png", b"\x89PNG\r\n\x1a\nfakepng", "image/png")}
    r = client.post(f"/v1/apps/hoodat/characters/{char['id']}/avatar/upload", files=files)
    assert r.status_code == 200
    assert r.json()["avatar_url"].endswith(f"/{char['id']}/avatar")
    got = client.get(f"/v1/apps/hoodat/characters/{char['id']}/avatar")
    assert got.status_code == 200
    assert got.content.startswith(b"\x89PNG")
    # avatar_path persisted on the character
    assert cs.get_character(char["id"])["avatar_path"].endswith("/avatar")


def test_avatar_upload_rejects_non_image(client):
    char = cs.create_character({"name": "Ada"})
    files = {"file": ("a.txt", b"hello", "text/plain")}
    r = client.post(f"/v1/apps/hoodat/characters/{char['id']}/avatar/upload", files=files)
    assert r.status_code == 422


def test_avatar_404_when_absent(client):
    char = cs.create_character({"name": "Ada"})
    assert client.get(f"/v1/apps/hoodat/characters/{char['id']}/avatar").status_code == 404
