"""Per-step reasoning ('thinking') control.

Thinking is the project default (DEFAULT_THINKING); only steps that explicitly
set ``thinking=False`` suppress it. The flag is realized as a per-request
``thinking_budget_tokens`` (0 = off, -1 = on) on the chat-completions body — no
model reload involved.
"""

from __future__ import annotations

import json

import httpx

from app.chain.models import (
    DEFAULT_THINKING,
    Alternative,
    ChainLLMConfig,
    ChainStep,
)
from app.chain.llm_client import OpenAICompatibleLLMClient
from app.chain.steps.llm import _strip_think_block


# ---- model: field + v1 hoist -----------------------------------------------

def test_alternative_thinking_defaults_to_none():
    assert Alternative(prompt="hi").thinking is None


def test_thinking_round_trips():
    assert Alternative(prompt="hi", thinking=False).thinking is False
    assert Alternative(prompt="hi", thinking=True).thinking is True


def test_flat_v1_step_hoists_thinking_into_alternative():
    step = ChainStep(name="s", type="llm", prompt="hi", thinking=False)
    assert step.primary.thinking is False


# ---- budget resolution (the executor's rule) -------------------------------

def _budget_for(alt: Alternative) -> int:
    thinking = alt.thinking if alt.thinking is not None else DEFAULT_THINKING
    return -1 if thinking else 0


def test_budget_off_when_thinking_false():
    assert _budget_for(Alternative(prompt="x", thinking=False)) == 0


def test_budget_on_when_thinking_true_or_default():
    assert _budget_for(Alternative(prompt="x", thinking=True)) == -1
    assert _budget_for(Alternative(prompt="x")) == -1  # None → DEFAULT_THINKING (on)


# ---- client puts thinking_budget_tokens on the wire ------------------------

def _capture_transport(captured: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch, captured: dict) -> None:
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = _capture_transport(captured)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


async def test_generate_sends_thinking_budget_at_top_level(monkeypatch):
    captured: dict = {}
    _patch_client(monkeypatch, captured)
    cfg = ChainLLMConfig(api_base="http://fake", model="m", thinking_budget_tokens=0)
    out = await OpenAICompatibleLLMClient().generate("hi", cfg)
    assert out == "ok"
    # Top-level field, NOT nested inside chat_template_kwargs.
    assert captured["body"]["thinking_budget_tokens"] == 0
    assert "chat_template_kwargs" not in captured["body"]


async def test_generate_omits_budget_when_unset(monkeypatch):
    captured: dict = {}
    _patch_client(monkeypatch, captured)
    cfg = ChainLLMConfig(api_base="http://fake", model="m")  # thinking_budget_tokens None
    await OpenAICompatibleLLMClient().generate("hi", cfg)
    assert "thinking_budget_tokens" not in captured["body"]


# ---- defensive <think> strip -----------------------------------------------

def test_strip_think_block_removes_leading_reasoning():
    assert _strip_think_block("<think>plan</think>Answer") == "Answer"
    assert _strip_think_block("  <think>\nmulti\nline\n</think>\n\nFinal") == "Final"


def test_strip_think_block_leaves_clean_output_untouched():
    assert _strip_think_block("Just an answer") == "Just an answer"
