from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from .models import ChainLLMConfig


class StreamChunk:
    """One streaming delta from ``chat_stream``.

    ``content`` is the text delta (may be empty for tool-call-only chunks).
    ``reasoning`` is the reasoning/thinking delta — llama.cpp emits it in
    ``delta.reasoning_content`` when a reasoning model runs with reasoning
    parsing on (``--reasoning-format``); it is kept separate from ``content`` so
    the final output never includes the think trace. ``tool_call_deltas``
    carries partial OpenAI tool-call fragments keyed by index; the caller
    assembles them. ``finish_reason`` is set on the last chunk that carries one
    (e.g. ``"stop"``, ``"tool_calls"``).
    """
    __slots__ = ("content", "reasoning", "tool_call_deltas", "finish_reason")

    def __init__(
        self,
        content: str = "",
        tool_call_deltas: Optional[list[dict]] = None,
        finish_reason: Optional[str] = None,
        reasoning: str = "",
    ):
        self.content = content
        self.reasoning = reasoning
        self.tool_call_deltas = tool_call_deltas or []
        self.finish_reason = finish_reason


class EmbedError(RuntimeError):
    """Raised when the embed server is unreachable or returns a bad response."""


class OpenAICompatibleLLMClient:
    async def embed(
        self,
        texts: list[str],
        *,
        api_base: str,
        model: str,
        timeout: float = 30.0,
    ) -> list[list[float]]:
        """Embed a batch of texts via an OpenAI-compatible ``/embeddings`` endpoint.

        POSTs ``{"input": texts, "model": model}`` in a single call and returns
        the vectors in input order. Errors (connect/timeout/HTTP/malformed) map
        to :class:`EmbedError` so callers degrade rather than crash.
        """
        if not texts:
            return []
        url = f"{api_base.rstrip('/')}/embeddings"
        payload = {"input": texts, "model": model}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as exc:
            raise EmbedError(f"embed server not reachable at {api_base}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise EmbedError(f"embed server timed out at {api_base}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise EmbedError(
                f"embed server returned {exc.response.status_code}: {exc}"
            ) from exc
        except ValueError as exc:
            raise EmbedError(f"embed server returned non-JSON body: {exc}") from exc
        try:
            items = data["data"]
            # Order by the response's `index` (OpenAI guarantees it maps to input order).
            ordered = sorted(items, key=lambda d: d.get("index", 0))
            return [list(d["embedding"]) for d in ordered]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbedError(f"malformed embeddings response: {exc}") from exc

    async def generate(self, prompt: str, llm_config: ChainLLMConfig) -> str:
        url = f"{llm_config.api_base.rstrip('/')}/chat/completions"
        payload = {
            "model": llm_config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": llm_config.temperature,
            "max_tokens": llm_config.max_tokens,
            "stream": False,
        }
        if llm_config.chat_template_kwargs:
            payload["chat_template_kwargs"] = llm_config.chat_template_kwargs
        if llm_config.thinking_budget_tokens is not None:
            payload["thinking_budget_tokens"] = llm_config.thinking_budget_tokens
        try:
            async with httpx.AsyncClient(timeout=llm_config.timeout_seconds) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"LLM server not reachable at {llm_config.api_base}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"LLM server timed out at {llm_config.api_base}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"LLM server returned {exc.response.status_code}: {exc}"
            ) from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Malformed LLM response: {exc}") from exc
        if not content:
            raise RuntimeError("LLM response has empty content")
        return content

    async def chat(
        self,
        messages: list[dict],
        llm_config: ChainLLMConfig,
        tools: list[dict] | None = None,
    ) -> dict:
        """Send a multi-turn messages list to the LLM. Returns raw choices[0] dict."""
        url = f"{llm_config.api_base.rstrip('/')}/chat/completions"
        payload: dict = {
            "model": llm_config.model,
            "messages": messages,
            "temperature": llm_config.temperature,
            "max_tokens": llm_config.max_tokens,
            "stream": False,
        }
        if tools:  # omit key entirely when empty — some servers reject []
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if llm_config.chat_template_kwargs:
            payload["chat_template_kwargs"] = llm_config.chat_template_kwargs
        if llm_config.thinking_budget_tokens is not None:
            payload["thinking_budget_tokens"] = llm_config.thinking_budget_tokens
        try:
            async with httpx.AsyncClient(timeout=llm_config.timeout_seconds) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"LLM server not reachable at {llm_config.api_base}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"LLM server timed out at {llm_config.api_base}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"LLM server returned {exc.response.status_code}: {exc}"
            ) from exc
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Malformed LLM response: {exc}") from exc
        # Carry token usage onto the choice so callers can log it without a second
        # round-trip (finish_reason already lives on the choice). Non-standard but
        # internal; callers that don't look for it are unaffected.
        if isinstance(choice, dict) and isinstance(data.get("usage"), dict):
            choice.setdefault("usage", data["usage"])
        return choice

    async def chat_stream(
        self,
        messages: list[dict],
        llm_config: ChainLLMConfig,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion as :class:`StreamChunk` instances.

        Consumes the OpenAI SSE protocol (``data: {...}`` frames, terminated by
        ``data: [DONE]`` or simply EOF). Yields one chunk per SSE frame; the
        caller accumulates content and tool calls as needed.
        """
        url = f"{llm_config.api_base.rstrip('/')}/chat/completions"
        payload: dict = {
            "model": llm_config.model,
            "messages": messages,
            "temperature": llm_config.temperature,
            "max_tokens": llm_config.max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if llm_config.chat_template_kwargs:
            payload["chat_template_kwargs"] = llm_config.chat_template_kwargs
        if llm_config.thinking_budget_tokens is not None:
            payload["thinking_budget_tokens"] = llm_config.thinking_budget_tokens
        try:
            async with httpx.AsyncClient(timeout=llm_config.timeout_seconds) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].lstrip()
                        if data_str == "[DONE]":
                            return
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content") or ""
                        reasoning = delta.get("reasoning_content") or ""
                        tool_call_deltas = delta.get("tool_calls") or []
                        finish_reason = choice.get("finish_reason")
                        if not (content or reasoning or tool_call_deltas or finish_reason):
                            continue
                        yield StreamChunk(
                            content=content,
                            reasoning=reasoning,
                            tool_call_deltas=list(tool_call_deltas),
                            finish_reason=finish_reason,
                        )
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"LLM server not reachable at {llm_config.api_base}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"LLM server timed out at {llm_config.api_base}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"LLM server returned {exc.response.status_code}: {exc}"
            ) from exc
