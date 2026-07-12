"""OpenAI-compatible LLM client.

Reads configuration from LLMConfig (env vars by default) and makes
HTTP requests to any OpenAI-compatible API endpoint.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Optional

from crb.config.settings import LLMConfig


class LLMError(Exception):
    """LLM API call failed."""


def _build_headers(config: LLMConfig) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }


def _build_payload(
    config: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
) -> bytes:
    body = {
        "model": config.model or "gpt-4o",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    return json.dumps(body).encode("utf-8")


def chat(
    config: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
) -> str:
    """Send a chat completion request to an OpenAI-compatible API.

    Args:
        config: LLM configuration (url, key, model).
        system_prompt: System-level instruction.
        user_prompt: User message content.
        temperature: Sampling temperature (default 0.3).

    Returns:
        The model's response text.

    Raises:
        LLMError: If the API call fails or returns an error.
    """
    if not config.is_valid():
        raise LLMError(
            "LLM not configured. Set CRB_LLM_API_URL and CRB_LLM_API_KEY "
            "in environment, or provide via config.yaml."
        )

    url = config.api_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    data = _build_payload(config, system_prompt, user_prompt, temperature)
    req = urllib.request.Request(
        url,
        data=data,
        headers=_build_headers(config),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise LLMError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Connection failed: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise LLMError(f"Invalid JSON response: {e}") from e

    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected response format: {e}") from e
