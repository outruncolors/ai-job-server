from __future__ import annotations

import asyncio

import httpx
import pytest


@pytest.fixture
def models_root(tmp_path, monkeypatch):
    """Point ComfyUI's models_root at a tmp dir and reset config + downloader."""
    import app.comfyui.config as cfg_mod
    import app.comfyui.downloader as dl_mod

    root = tmp_path / "models"
    root.mkdir()
    cfg = cfg_mod.ComfyUIConfig(models_root=str(root))
    cfg_mod.save_config(cfg)
    dl_mod.reset_downloader()
    yield root
    dl_mod.reset_downloader()


def _install_mock_transport(monkeypatch, handler):
    """Force the downloader's httpx.AsyncClient to use a MockTransport."""
    import app.comfyui.downloader as dl_mod
    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        dl_mod.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client_cls(
            transport=transport,
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    )


# ── Path safety ─────────────────────────────────────────────────────────────


def test_rejects_absolute_path(models_root):
    from app.comfyui.downloader import DownloadError, get_downloader
    with pytest.raises(DownloadError) as exc:
        get_downloader().start("https://x/y", "/etc/passwd")
    assert exc.value.status_code == 422


def test_rejects_parent_traversal(models_root):
    from app.comfyui.downloader import DownloadError, get_downloader
    with pytest.raises(DownloadError) as exc:
        get_downloader().start("https://x/y", "../escape.bin")
    assert exc.value.status_code == 422


def test_rejects_empty_path(models_root):
    from app.comfyui.downloader import DownloadError, get_downloader
    with pytest.raises(DownloadError) as exc:
        get_downloader().start("https://x/y", "   ")
    assert exc.value.status_code == 422


def test_rejects_non_http_url(models_root):
    from app.comfyui.downloader import DownloadError, get_downloader
    with pytest.raises(DownloadError) as exc:
        get_downloader().start("file:///etc/passwd", "ok.bin")
    assert exc.value.status_code == 422


async def test_strips_leading_models_prefix(models_root, monkeypatch):
    from app.comfyui.downloader import get_downloader

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, content=b"hi", headers={"content-length": "2"}),
    )
    state = get_downloader().start("https://x/y", "models/checkpoints/a.bin")
    await state.task
    assert state.path == "checkpoints/a.bin"


# ── Existing-file handling ──────────────────────────────────────────────────


def test_rejects_existing_file_without_overwrite(models_root):
    from app.comfyui.downloader import DownloadError, get_downloader
    existing = models_root / "checkpoints" / "foo.bin"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"already here")

    with pytest.raises(DownloadError) as exc:
        get_downloader().start("https://x/y", "checkpoints/foo.bin")
    assert exc.value.status_code == 409


async def test_allows_existing_file_with_overwrite(models_root, monkeypatch):
    from app.comfyui.downloader import get_downloader
    existing = models_root / "foo.bin"
    existing.write_bytes(b"old")

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, content=b"new bytes", headers={"content-length": "9"}),
    )
    state = get_downloader().start("https://x/y", "foo.bin", overwrite=True)
    await state.task
    assert state.status == "done"
    assert existing.read_bytes() == b"new bytes"


# ── Happy path / errors / cancel ────────────────────────────────────────────


async def test_download_writes_file_and_marks_done(models_root, monkeypatch):
    from app.comfyui.downloader import get_downloader

    payload = b"x" * 4096

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://example.com/model.bin"
        return httpx.Response(200, content=payload, headers={"content-length": str(len(payload))})

    _install_mock_transport(monkeypatch, handler)
    state = get_downloader().start("https://example.com/model.bin", "sub/dir/model.bin")
    await state.task

    assert state.status == "done"
    assert state.bytes_done == len(payload)
    assert state.bytes_total == len(payload)
    dest = models_root / "sub" / "dir" / "model.bin"
    assert dest.read_bytes() == payload
    # partial file removed
    assert not dest.with_name(dest.name + ".partial").exists()


async def test_download_sends_authorization_header(models_root, monkeypatch):
    from app.comfyui.downloader import get_downloader

    seen_auth: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth.append(req.headers.get("authorization"))
        return httpx.Response(200, content=b"ok", headers={"content-length": "2"})

    _install_mock_transport(monkeypatch, handler)
    # Bare token should be auto-wrapped as Bearer.
    state = get_downloader().start(
        "https://example.com/gated.bin", "gated.bin", authorization="hf_secret123"
    )
    await state.task
    assert state.status == "done"
    assert seen_auth == ["Bearer hf_secret123"]
    # Token is never exposed in the public state dict.
    pub = state.to_public()
    assert "hf_secret123" not in str(pub)


async def test_download_authorization_preserves_explicit_scheme(models_root, monkeypatch):
    from app.comfyui.downloader import get_downloader

    seen_auth: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_auth.append(req.headers.get("authorization"))
        return httpx.Response(200, content=b"ok", headers={"content-length": "2"})

    _install_mock_transport(monkeypatch, handler)
    state = get_downloader().start(
        "https://example.com/gated.bin",
        "gated2.bin",
        authorization="Basic dXNlcjpwYXNz",
    )
    await state.task
    assert seen_auth == ["Basic dXNlcjpwYXNz"]


async def test_download_http_error_sets_error_state(models_root, monkeypatch):
    from app.comfyui.downloader import get_downloader

    _install_mock_transport(monkeypatch, lambda req: httpx.Response(404, content=b"nope"))
    state = get_downloader().start("https://example.com/missing.bin", "missing.bin")
    await state.task

    assert state.status == "error"
    assert "404" in (state.error or "")
    assert not (models_root / "missing.bin").exists()
    assert not (models_root / "missing.bin.partial").exists()


async def test_download_cancel_removes_partial(models_root, monkeypatch):
    from app.comfyui.downloader import get_downloader

    # Stream slowly so we can cancel mid-flight.
    async def slow_stream():
        for _ in range(50):
            await asyncio.sleep(0.02)
            yield b"x" * 1024

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=slow_stream())

    _install_mock_transport(monkeypatch, handler)
    state = get_downloader().start("https://example.com/big.bin", "big.bin")
    await asyncio.sleep(0.05)
    ok = await get_downloader().cancel(state.id)

    assert ok is True
    assert state.status == "cancelled"
    assert not (models_root / "big.bin").exists()
    assert not (models_root / "big.bin.partial").exists()


# ── Router integration ─────────────────────────────────────────────────────


def test_router_start_returns_id(models_root, monkeypatch, client):
    monkeypatch.setattr(
        "app.comfyui.downloader.httpx.AsyncClient",
        # Won't actually be called before the response — we use a never-resolves stream
        lambda *a, **kw: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"")),
        ),
    )
    r = client.post(
        "/v1/comfyui/downloads",
        json={"url": "https://example.com/m.bin", "path": "x.bin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "id" in body
    assert body["path"] == "x.bin"


def test_router_rejects_bad_path(models_root, client):
    r = client.post(
        "/v1/comfyui/downloads",
        json={"url": "https://x/y", "path": "../escape"},
    )
    assert r.status_code == 422


def test_router_list_and_get(models_root, monkeypatch, client):
    monkeypatch.setattr(
        "app.comfyui.downloader.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"hi")),
        ),
    )
    r = client.post(
        "/v1/comfyui/downloads",
        json={"url": "https://example.com/a.bin", "path": "a.bin"},
    )
    download_id = r.json()["id"]

    listed = client.get("/v1/comfyui/downloads").json()
    assert any(it["id"] == download_id for it in listed["items"])

    got = client.get(f"/v1/comfyui/downloads/{download_id}").json()
    assert got["id"] == download_id
    assert got["path"] == "a.bin"
