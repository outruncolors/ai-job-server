from __future__ import annotations

import httpx

from .models import ChainLLMConfig


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
