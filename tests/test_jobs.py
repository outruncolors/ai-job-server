from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


# ---------------------------------------------------------------------------
# Image job creation (workflow-based schema)
# ---------------------------------------------------------------------------

def test_create_image_job(client):
    payload = {"workflow": "txt2img", "prompt": "a cat on the moon"}
    r = client.post("/v1/jobs/image", json=payload)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_type"] == "image"
    assert "job_id" in body
    assert "created_at" in body


def test_create_image_job_missing_workflow(client):
    r = client.post("/v1/jobs/image", json={"prompt": "hi"})
    assert r.status_code == 422


def test_create_image_job_missing_prompt(client):
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img"})
    assert r.status_code == 422


def test_image_job_files_written(client, tmp_path):
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "test prompt"})
    job_id = r.json()["job_id"]

    job_dirs = list(tmp_path.glob(f"*/{job_id}"))
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]

    assert (job_dir / "request.json").exists()
    assert (job_dir / "input.txt").exists()
    assert (job_dir / "status.json").exists()
    assert (job_dir / "logs.txt").exists()
    assert (job_dir / "artifacts.json").exists()

    status = json.loads((job_dir / "status.json").read_text())
    assert status["status"] == "queued"
    assert status["job_type"] == "image"

    input_text = (job_dir / "input.txt").read_text()
    assert "test prompt" in input_text

    artifacts = json.loads((job_dir / "artifacts.json").read_text())
    assert artifacts == []

    logs = (job_dir / "logs.txt").read_text()
    assert logs == ""


def test_image_job_resolves_prompt_server_side(client, tmp_path):
    # The browser sends RAW text; the server resolves it (here, an unknown var
    # falls back to its literal) and returns the authoritative draw for the UI.
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "a {{var.who}} cat"})
    assert r.status_code == 202
    body = r.json()
    assert body["resolved_items"] == [
        {"resolved": "a who cat", "substitutions": [{"token": "{{var.who}}", "value": "who"}]}
    ]
    # The persisted job text is the resolved text (backend = source of truth).
    job_dir = next(iter(tmp_path.glob(f"*/{body['job_id']}")))
    assert (job_dir / "input.txt").read_text() == "a who cat"


# ---------------------------------------------------------------------------
# Voice job creation
# ---------------------------------------------------------------------------

def test_create_voice_job(client):
    payload = {"text": "Hello world", "speed": 1.0}
    r = client.post("/v1/jobs/voice", json=payload)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_type"] == "voice"


def test_voice_job_resolves_text_and_segments(client):
    r = client.post("/v1/jobs/voice", json={"text": "say {{var.x}}"})
    assert r.json()["resolved_items"] == [
        {"resolved": "say x", "substitutions": [{"token": "{{var.x}}", "value": "x"}]}
    ]
    r2 = client.post(
        "/v1/jobs/voice", json={"segments": [{"text": "{{var.a}}"}, {"text": "{{var.b}}"}]}
    )
    items = r2.json()["resolved_items"]
    assert [i["resolved"] for i in items] == ["a", "b"]
    assert items[0]["label"] == "Segment 1"


def test_create_voice_job_with_options(client):
    payload = {"text": "Hello", "voice": "en-US-1", "speed": 1.2, "language": "en"}
    r = client.post("/v1/jobs/voice", json=payload)
    assert r.status_code == 202


def test_create_voice_job_missing_text(client):
    r = client.post("/v1/jobs/voice", json={"speed": 1.0})
    assert r.status_code == 422


def test_voice_job_files_written(client, tmp_path):
    r = client.post("/v1/jobs/voice", json={"text": "say this"})
    job_id = r.json()["job_id"]

    job_dirs = list(tmp_path.glob(f"*/{job_id}"))
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]

    request_data = json.loads((job_dir / "request.json").read_text())
    assert request_data["job_type"] == "voice"
    assert request_data["requested"]["text"] == "say this"

    input_text = (job_dir / "input.txt").read_text()
    assert "say this" in input_text


# ---------------------------------------------------------------------------
# Job lookup
# ---------------------------------------------------------------------------

def test_get_job(client):
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "test"})
    job_id = r.json()["job_id"]

    r2 = client.get(f"/v1/jobs/{job_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["job_id"] == job_id
    assert body["status"] == "queued"
    assert body["job_type"] == "image"


def test_get_job_not_found(client):
    r = client.get("/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_list_jobs_empty(client):
    r = client.get("/v1/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["jobs"] == []
    assert body["total"] == 0


def test_list_jobs(client):
    client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "test"})
    client.post("/v1/jobs/voice", json={"text": "second"})
    r = client.get("/v1/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    types = {j["job_type"] for j in body["jobs"]}
    assert types == {"image", "voice"}


# ---------------------------------------------------------------------------
# File download
# ---------------------------------------------------------------------------

def test_get_job_file_status(client):
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "test"})
    job_id = r.json()["job_id"]

    r2 = client.get(f"/v1/jobs/{job_id}/files/status.json")
    assert r2.status_code == 200
    data = json.loads(r2.content)
    assert data["job_id"] == job_id


def test_get_job_file_logs(client):
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "test"})
    job_id = r.json()["job_id"]

    r2 = client.get(f"/v1/jobs/{job_id}/files/logs.txt")
    assert r2.status_code == 200
    assert r2.content == b""


def test_get_job_file_not_found(client):
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "test"})
    job_id = r.json()["job_id"]
    r2 = client.get(f"/v1/jobs/{job_id}/files/output.png")
    assert r2.status_code == 404


def test_get_job_file_path_traversal(client):
    r = client.post("/v1/jobs/image", json={"workflow": "txt2img", "prompt": "test"})
    job_id = r.json()["job_id"]
    r2 = client.get(f"/v1/jobs/{job_id}/files/../../etc/passwd")
    assert r2.status_code in (404, 422)
