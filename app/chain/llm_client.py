from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from .models import ChainLLMConfig


class StreamChunk:
    """One streaming delta from ``chat_stream``.

    ``content`` is the text delta (may be empty for tool-call-only chunks).
    ``tool_call_deltas`` carries partial OpenAI tool-call fragments keyed by
    index; the caller assembles them. ``finish_reason`` is set on the last
    chunk that carries one (e.g. ``"stop"``, ``"tool_calls"``).
    """
    __slots__ = ("content", "tool_call_deltas", "finish_reason")

    def __init__(
        self,
        content: str = "",
        tool_call_deltas: Optional[list[dict]] = None,
        finish_reason: Optional[str] = None,
    ):
        self.content = content
        self.tool_call_deltas = tool_call_deltas or []
        self.finish_reason = finish_reason


class OpenAICompatibleLLMClient:
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
            return data["choices"][0]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Malformed LLM response: {exc}") from exc

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
                        tool_call_deltas = delta.get("tool_calls") or []
                        finish_reason = choice.get("finish_reason")
                        if not (content or tool_call_deltas or finish_reason):
                            continue
                        yield StreamChunk(
                            content=content,
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
