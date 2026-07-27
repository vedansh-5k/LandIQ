"""
catalog.py  (from student's LLM Configurator — adapted for LandIQ)
----------
Queries litellm.model_cost to return all available models (~2250 chat models).
This is the source of truth for the Model Catalogue endpoint.
"""

import litellm
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def get_all_chat_models(
    provider_filter: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 500,
) -> List[dict]:
    """
    Returns chat models from litellm.model_cost.
    Filters by provider or search query if provided.
    Returns dicts ready to be serialised as JSON.
    """
    results = []

    for model_key, details in litellm.model_cost.items():
        try:
            if model_key == "sample_spec":
                continue
            if not isinstance(details, dict):
                continue
            if details.get("mode") != "chat":
                continue

            provider = str(details.get("litellm_provider") or "other").lower()

            if provider_filter and provider_filter.lower() != provider:
                continue
            if query and query.lower() not in model_key.lower():
                continue

            max_tokens = details.get("max_tokens")
            try:
                max_tokens = int(max_tokens) if max_tokens is not None else None
            except (ValueError, TypeError):
                max_tokens = None

            max_output = details.get("max_output_tokens")
            try:
                max_output = int(max_output) if max_output is not None else None
            except (ValueError, TypeError):
                max_output = None

            input_cost = details.get("input_cost_per_token")
            output_cost = details.get("output_cost_per_token")

            # Format cost string
            if input_cost is not None:
                cost_str = f"${input_cost * 1_000_000:.2f}/1M"
            else:
                cost_str = "Free / Unknown"

            results.append({
                "model_key":        model_key,
                "provider":         provider,
                "mode":             details.get("mode", "chat"),
                "supports_vision":  bool(details.get("supports_vision", False)),
                "max_tokens":       max_tokens,
                "max_output_tokens": max_output,
                "input_cost_per_token":  input_cost,
                "output_cost_per_token": output_cost,
                "cost_display":     cost_str,
            })

        except Exception as e:
            logger.warning(f"Skipping model {model_key}: {e}")
            continue

    # Sort: known providers first, then alphabetical
    PROVIDER_ORDER = ["groq", "gemini", "anthropic", "openai", "mistral",
                      "deepseek", "cohere", "together_ai", "perplexity"]

    def sort_key(m):
        try:
            idx = PROVIDER_ORDER.index(m["provider"])
        except ValueError:
            idx = len(PROVIDER_ORDER)
        return (idx, m["model_key"])

    results.sort(key=sort_key)

    return results[:limit]


def get_unique_providers() -> List[str]:
    """Returns sorted list of unique providers that have chat models."""
    providers = set()
    for model_key, details in litellm.model_cost.items():
        if model_key == "sample_spec":
            continue
        if not isinstance(details, dict):
            continue
        if details.get("mode") != "chat":
            continue
        p = details.get("litellm_provider")
        if p:
            providers.add(str(p).lower())
    return sorted(providers)