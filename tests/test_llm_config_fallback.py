from __future__ import annotations

import pytest

import app.llamacpp.config as llamacpp_config
import app.server as server
from app import llm_config


@pytest.fixture(autouse=True)
def no_endpoint_preset(tmp_path, monkeypatch):
    """Ensure no default endpoint preset is configured (force the fallback)."""
    monkeypatch.setattr(llm_config, "CONFIG_PATH", tmp_path / "llm_config.json")


def test_fallback_to_local_llama_server_when_node_has_llm(monkeypatch):
    monkeypatch.setattr(server, "get_local_capabilities", lambda: {"web", "llm"})
    monkeypatch.setattr(
        llamacpp_config, "get_config",
        lambda: llamacpp_config.LlamaCppConfig(port=9001, default_preset="my-model"),
    )
    cfg = llm_config.get_default_as_chain_llm_config()
    assert cfg.api_base == "http://127.0.0.1:9001/v1"
    assert cfg.model == "my-model"


def test_fallback_to_llm_peer_when_node_lacks_llm(monkeypatch):
    monkeypatch.setattr(server, "get_local_capabilities", lambda: {"web", "voice"})
    monkeypatch.setattr(
        server, "find_peer_for_capability",
        lambda cap: server.Peer(name="gpu", host="gpu.local", port=8090, capabilities=["llm"]),
    )
    cfg = llm_config.get_default_as_chain_llm_config()
    # Placeholder pointing at the peer; ensure_loaded_for_step refines it per step.
    assert cfg.api_base == "http://gpu.local:8080/v1"


def test_raises_only_when_no_llm_node_anywhere(monkeypatch):
    monkeypatch.setattr(server, "get_local_capabilities", lambda: {"web"})
    monkeypatch.setattr(server, "find_peer_for_capability", lambda cap: None)
    with pytest.raises(RuntimeError):
        llm_config.get_default_as_chain_llm_config()


def test_explicit_preset_still_wins(monkeypatch):
    monkeypatch.setattr(
        llm_config, "get_default",
        lambda: llm_config.LLMPreset(
            id="p1", name="endpoint", api_base="http://configured/v1", model="cfg-model"
        ),
    )
    cfg = llm_config.get_default_as_chain_llm_config()
    assert cfg.api_base == "http://configured/v1"
    assert cfg.model == "cfg-model"


async def test_swap_routes_to_peer_with_no_preset(monkeypatch):
    """Multi-machine + no preset: the step still routes to the peer's llama-server."""
    from app.chain import llm_swap
    from app.chain.models import Alternative, ChainLLMConfig, ChainStep

    monkeypatch.setattr(server, "get_local_capabilities", lambda: {"web"})
    monkeypatch.setattr(llm_swap, "resolve_preset_name", lambda alt: None)
    monkeypatch.setattr(llm_swap, "resolve_llm_peer_api_base", lambda: "http://gpu.local:8090")

    async def fake_server_url(api_base):
        return "http://gpu.local:8080"

    monkeypatch.setattr(llm_swap, "resolve_llm_server_url", fake_server_url)

    base = ChainLLMConfig(api_base="http://placeholder/v1", model="default")
    step = ChainStep(number=1, name="s", type="llm", alternatives=[Alternative()])
    new_llm, preset, log = await llm_swap.ensure_loaded_for_step(step, step.alternatives[0], base, None)
    assert new_llm.api_base == "http://gpu.local:8080/v1"
    assert log and "no swap" in log
