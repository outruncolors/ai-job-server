from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def patch_image_prompts_dir(tmp_path, monkeypatch):
    import app.image_prompts as ip
    d = tmp_path / "image_prompts"
    monkeypatch.setattr(ip, "PROMPTS_DIR", d)
    monkeypatch.setattr(ip, "INDEX_PATH", d / "index.json")


# ---------------------------------------------------------------------------
# Storage-layer unit tests
# ---------------------------------------------------------------------------

def test_list_prompts_empty():
    from app.image_prompts import list_prompts
    assert list_prompts() == []


def test_create_and_list_prompt():
    from app.image_prompts import create_prompt, list_prompts
    entry = create_prompt("Portrait", "a portrait of a cat", workflow="sdxl")
    assert entry["name"] == "Portrait"
    assert entry["prompt"] == "a portrait of a cat"
    assert entry["workflow"] == "sdxl"
    assert "id" in entry
    assert "created_at" in entry
    assert "updated_at" in entry
    entries = list_prompts()
    assert len(entries) == 1
    assert entries[0]["id"] == entry["id"]


def test_create_prompt_workflow_optional():
    from app.image_prompts import create_prompt
    entry = create_prompt("Generic", "a sunset")
    assert entry["workflow"] is None


def test_create_prompt_empty_name_rejected():
    from app.image_prompts import create_prompt
    with pytest.raises(ValueError, match="name is required"):
        create_prompt("   ", "anything")


def test_create_prompt_empty_prompt_rejected():
    from app.image_prompts import create_prompt
    with pytest.raises(ValueError, match="prompt is required"):
        create_prompt("Name", "")


def test_unique_name_conflict():
    from app.image_prompts import create_prompt
    e1 = create_prompt("Dup", "a")
    e2 = create_prompt("Dup", "b")
    assert e1["name"] == "Dup"
    assert e2["name"] == "Dup (2)"


def test_unique_name_multiple_conflicts():
    from app.image_prompts import create_prompt
    create_prompt("X", "a")
    create_prompt("X", "b")
    e3 = create_prompt("X", "c")
    assert e3["name"] == "X (3)"


def test_get_prompt():
    from app.image_prompts import create_prompt, get_prompt
    entry = create_prompt("Find", "test prompt")
    found = get_prompt(entry["id"])
    assert found is not None
    assert found["name"] == "Find"


def test_get_prompt_missing():
    from app.image_prompts import get_prompt
    assert get_prompt("00000000-0000-0000-0000-000000000000") is None


def test_update_prompt():
    from app.image_prompts import create_prompt, get_prompt, update_prompt
    entry = create_prompt("Old", "old text")
    result = update_prompt(entry["id"], prompt="new text", workflow="flux")
    assert result is not None
    assert result["prompt"] == "new text"
    assert result["workflow"] == "flux"
    assert result["name"] == "Old"
    # Verify it persisted
    fresh = get_prompt(entry["id"])
    assert fresh["prompt"] == "new text"


def test_update_prompt_name_unique_among_others():
    from app.image_prompts import create_prompt, update_prompt
    create_prompt("Taken", "x")
    other = create_prompt("Free", "y")
    result = update_prompt(other["id"], name="Taken")
    assert result["name"] == "Taken (2)"


def test_update_prompt_keep_same_name():
    from app.image_prompts import create_prompt, update_prompt
    entry = create_prompt("Same", "x")
    result = update_prompt(entry["id"], name="Same")
    # Updating to the same name should keep it (not add suffix), because the
    # entry being updated is excluded from the uniqueness check.
    assert result["name"] == "Same"


def test_update_prompt_empty_name_rejected():
    from app.image_prompts import create_prompt, update_prompt
    entry = create_prompt("Name", "x")
    with pytest.raises(ValueError, match="name is required"):
        update_prompt(entry["id"], name="  ")


def test_update_prompt_ignores_unknown_fields():
    from app.image_prompts import create_prompt, update_prompt
    entry = create_prompt("Name", "x")
    result = update_prompt(entry["id"], id="hacked", created_at="2000")
    assert result["id"] == entry["id"]
    assert result["created_at"] == entry["created_at"]


def test_update_prompt_missing():
    from app.image_prompts import update_prompt
    assert update_prompt("00000000-0000-0000-0000-000000000000", prompt="x") is None


def test_delete_prompt():
    from app.image_prompts import create_prompt, delete_prompt, list_prompts
    entry = create_prompt("Doomed", "x")
    assert delete_prompt(entry["id"]) is True
    assert list_prompts() == []


def test_delete_prompt_missing():
    from app.image_prompts import delete_prompt
    assert delete_prompt("00000000-0000-0000-0000-000000000000") is False


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

def test_get_prompts_empty(client):
    r = client.get("/v1/image-prompts")
    assert r.status_code == 200
    assert r.json() == {"prompts": []}


def test_post_prompt(client):
    r = client.post(
        "/v1/image-prompts",
        json={"name": "Test", "prompt": "a test prompt", "workflow": "sdxl"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Test"
    assert body["prompt"] == "a test prompt"
    assert body["workflow"] == "sdxl"


def test_post_prompt_workflow_optional(client):
    r = client.post(
        "/v1/image-prompts",
        json={"name": "Generic", "prompt": "a sunset"},
    )
    assert r.status_code == 201
    assert r.json()["workflow"] is None


def test_post_prompt_empty_name_422(client):
    r = client.post(
        "/v1/image-prompts",
        json={"name": "", "prompt": "a prompt"},
    )
    assert r.status_code == 422


def test_post_prompt_dedup(client):
    client.post("/v1/image-prompts", json={"name": "Dup", "prompt": "a"})
    r2 = client.post("/v1/image-prompts", json={"name": "Dup", "prompt": "b"})
    assert r2.status_code == 201
    assert r2.json()["name"] == "Dup (2)"


def test_list_after_create(client):
    client.post("/v1/image-prompts", json={"name": "Listed", "prompt": "hi"})
    r = client.get("/v1/image-prompts")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()["prompts"]]
    assert "Listed" in names


def test_get_prompt_endpoint(client):
    r = client.post("/v1/image-prompts", json={"name": "One", "prompt": "p"})
    pid = r.json()["id"]
    r2 = client.get(f"/v1/image-prompts/{pid}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "One"


def test_get_prompt_endpoint_404(client):
    r = client.get("/v1/image-prompts/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_put_prompt_endpoint(client):
    r = client.post(
        "/v1/image-prompts",
        json={"name": "Editable", "prompt": "old"},
    )
    pid = r.json()["id"]
    r2 = client.put(
        f"/v1/image-prompts/{pid}",
        json={"prompt": "new", "workflow": "flux"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["prompt"] == "new"
    assert body["workflow"] == "flux"


def test_put_prompt_endpoint_404(client):
    r = client.put(
        "/v1/image-prompts/00000000-0000-0000-0000-000000000000",
        json={"prompt": "x"},
    )
    assert r.status_code == 404


def test_delete_prompt_endpoint(client):
    r = client.post("/v1/image-prompts", json={"name": "Gone", "prompt": "x"})
    pid = r.json()["id"]
    r2 = client.delete(f"/v1/image-prompts/{pid}")
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    r3 = client.get("/v1/image-prompts")
    assert r3.json() == {"prompts": []}


def test_delete_prompt_endpoint_404(client):
    r = client.delete("/v1/image-prompts/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
