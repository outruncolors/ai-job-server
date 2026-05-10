from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Storage-layer unit tests
# ---------------------------------------------------------------------------

def test_list_presets_empty():
    from app.voice_presets import list_presets
    assert list_presets() == []


def test_save_and_list_preset():
    from app.voice_presets import list_presets, save_preset
    entry = save_preset("Alice", "hello world", b"RIFF_fake_wav")
    assert entry["name"] == "Alice"
    assert entry["caption"] == "hello world"
    assert "id" in entry
    entries = list_presets()
    assert len(entries) == 1
    assert entries[0]["id"] == entry["id"]


def test_save_writes_wav_file(tmp_path, monkeypatch):
    import app.voice_presets as vp
    monkeypatch.setattr(vp, "PRESETS_DIR", tmp_path / "vp")
    monkeypatch.setattr(vp, "INDEX_PATH", tmp_path / "vp" / "index.json")
    entry = vp.save_preset("Bob", "hi", b"RIFF_data")
    assert (tmp_path / "vp" / entry["wav_filename"]).read_bytes() == b"RIFF_data"


def test_unique_name_conflict():
    from app.voice_presets import save_preset
    e1 = save_preset("Bob", "hi", b"wav1")
    e2 = save_preset("Bob", "there", b"wav2")
    assert e1["name"] == "Bob"
    assert e2["name"] == "Bob (2)"


def test_unique_name_multiple_conflicts():
    from app.voice_presets import save_preset
    save_preset("X", "a", b"1")
    save_preset("X", "b", b"2")
    e3 = save_preset("X", "c", b"3")
    assert e3["name"] == "X (3)"


def test_get_preset():
    from app.voice_presets import get_preset, save_preset
    entry = save_preset("Carol", "test", b"wav")
    found = get_preset(entry["id"])
    assert found is not None
    assert found["name"] == "Carol"


def test_get_preset_missing():
    from app.voice_presets import get_preset
    assert get_preset("00000000-0000-0000-0000-000000000000") is None


def test_delete_preset():
    from app.voice_presets import delete_preset, list_presets, resolve_preset_wav, save_preset
    entry = save_preset("Dave", "test", b"wav")
    assert delete_preset(entry["id"]) is True
    assert list_presets() == []
    assert resolve_preset_wav(entry["id"]) is None


def test_delete_nonexistent():
    from app.voice_presets import delete_preset
    assert delete_preset("00000000-0000-0000-0000-000000000000") is False


def test_resolve_preset_wav():
    from app.voice_presets import resolve_preset_wav, save_preset
    entry = save_preset("Eve", "hi", b"RIFF_wav")
    path = resolve_preset_wav(entry["id"])
    assert path is not None
    assert path.exists()


def test_resolve_preset_wav_missing_file():
    from app.voice_presets import resolve_preset_wav, save_preset
    import app.voice_presets as vp
    entry = save_preset("Frank", "yo", b"wav")
    # Manually remove the wav
    (vp.PRESETS_DIR / entry["wav_filename"]).unlink()
    assert resolve_preset_wav(entry["id"]) is None


def test_save_preset_from_job(tmp_path, monkeypatch):
    import app.jobs as jobs_module
    from app.voice_presets import list_presets, save_preset_from_job

    # Create a fake job dir with output.wav
    job_dir = tmp_path / "2026-05-10" / "test-job-abc"
    job_dir.mkdir(parents=True)
    (job_dir / "output.wav").write_bytes(b"RIFF_job_wav")
    monkeypatch.setattr(jobs_module, "JOBS_BASE", tmp_path)

    entry = save_preset_from_job("test-job-abc", "Echo", "spoken text")
    assert entry["name"] == "Echo"
    assert entry["caption"] == "spoken text"
    assert len(list_presets()) == 1


def test_save_preset_from_job_missing_job():
    from app.voice_presets import save_preset_from_job
    with pytest.raises(FileNotFoundError, match="not found"):
        save_preset_from_job("nonexistent-job-id", "X", "y")


def test_save_preset_from_job_missing_wav(tmp_path, monkeypatch):
    import app.jobs as jobs_module
    from app.voice_presets import save_preset_from_job

    job_dir = tmp_path / "2026-05-10" / "test-job-nowav"
    job_dir.mkdir(parents=True)
    # No output.wav written
    monkeypatch.setattr(jobs_module, "JOBS_BASE", tmp_path)

    with pytest.raises(FileNotFoundError, match="output.wav missing"):
        save_preset_from_job("test-job-nowav", "Y", "z")


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

def test_get_presets_empty(client):
    r = client.get("/v1/voice-presets")
    assert r.status_code == 200
    assert r.json() == []


def test_post_preset(client):
    r = client.post(
        "/v1/voice-presets",
        data={"name": "Test", "caption": "hello there"},
        files={"file": ("voice.wav", b"RIFF_fake", "audio/wav")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Test"
    assert body["caption"] == "hello there"
    assert "id" in body
    assert body["wav_filename"].endswith(".wav")


def test_post_preset_non_wav_rejected(client):
    r = client.post(
        "/v1/voice-presets",
        data={"name": "Bad", "caption": "test"},
        files={"file": ("voice.mp3", b"ID3_fake", "audio/mpeg")},
    )
    assert r.status_code == 422


def test_post_preset_dedup(client):
    client.post(
        "/v1/voice-presets",
        data={"name": "Dup", "caption": "a"},
        files={"file": ("v.wav", b"R", "audio/wav")},
    )
    r2 = client.post(
        "/v1/voice-presets",
        data={"name": "Dup", "caption": "b"},
        files={"file": ("v.wav", b"R", "audio/wav")},
    )
    assert r2.json()["name"] == "Dup (2)"


def test_list_presets_after_create(client):
    client.post(
        "/v1/voice-presets",
        data={"name": "Listed", "caption": "hi"},
        files={"file": ("v.wav", b"R", "audio/wav")},
    )
    r = client.get("/v1/voice-presets")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "Listed" in names


def test_delete_preset_endpoint(client):
    r = client.post(
        "/v1/voice-presets",
        data={"name": "ToDelete", "caption": "gone"},
        files={"file": ("v.wav", b"RIFF", "audio/wav")},
    )
    preset_id = r.json()["id"]
    r2 = client.delete(f"/v1/voice-presets/{preset_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == preset_id

    r3 = client.get("/v1/voice-presets")
    assert r3.json() == []


def test_delete_nonexistent_endpoint(client):
    r = client.delete("/v1/voice-presets/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_from_job_endpoint(client, tmp_path, monkeypatch):
    import app.jobs as jobs_module

    job_dir = tmp_path / "2026-05-10" / "test-job-999"
    job_dir.mkdir(parents=True)
    (job_dir / "output.wav").write_bytes(b"RIFF_job_wav")
    monkeypatch.setattr(jobs_module, "JOBS_BASE", tmp_path)

    r = client.post(
        "/v1/voice-presets/from-job",
        json={"job_id": "test-job-999", "name": "FromJob", "caption": "spoken words"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "FromJob"
    assert body["caption"] == "spoken words"


def test_from_job_endpoint_missing_job(client):
    r = client.post(
        "/v1/voice-presets/from-job",
        json={"job_id": "no-such-job", "name": "X", "caption": "y"},
    )
    assert r.status_code == 404
