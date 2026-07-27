"""
llm_proxy_client.py
--------------------
Used by LandIQ's 8 agents to call an active LLM Configuration
through the /llm/{full_name}/chat proxy — gets real priority-based
fallback (e.g. Llama -> Gemini) and rate limiting, exactly as
configured on the LLM Configuration page.

This REPLACES direct llm = ChatGroq(...) construction in agents
when an LLM Configuration is selected (instead of a raw model).
"""

import os
import httpx
from typing import Optional

# Where the FastAPI server is running (same process, but proxy calls
# go through the actual HTTP route so rate limiting / logging / PII
# masking in api.py all apply for real).
BASE_URL = os.getenv("LANDIQ_INTERNAL_URL", "http://localhost:8000")


class ProxyLLMError(Exception):
    pass


def call_llm_configuration(
    full_name: str,
    messages: list,
    agent_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.3,
    timeout: float = 60.0,
) -> dict:
    """
    Calls POST /llm/{full_name}/chat synchronously.
    Returns the raw response dict (OpenAI-style: choices, usage, model_used).
    Raises ProxyLLMError on failure (e.g. config not found, all models exhausted).
    """
    url = f"{BASE_URL}/llm/{full_name}/chat"
    payload = {"messages": messages, "temperature": temperature}
    if max_tokens:
        payload["max_tokens"] = max_tokens

    headers = {}
    if agent_id:
        headers["x-agent-id"] = agent_id

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            raise ProxyLLMError(f"Rate limit hit for config '{full_name}': {resp.text}")
        if resp.status_code == 404:
            raise ProxyLLMError(f"LLM Configuration '{full_name}' not found or disabled.")
        if resp.status_code >= 400:
            raise ProxyLLMError(f"Proxy call failed ({resp.status_code}): {resp.text}")
        return resp.json()
    except httpx.RequestError as e:
        raise ProxyLLMError(f"Could not reach LandIQ proxy at {url}: {e}")


def get_text_from_proxy_response(response: dict) -> str:
    """Extracts assistant text content from the proxy's OpenAI-style response."""
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""