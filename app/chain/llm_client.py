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
