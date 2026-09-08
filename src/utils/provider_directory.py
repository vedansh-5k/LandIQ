"""
provider_directory.py — LandIQ LLM Configurator
------------------------------------------------
A curated, human-friendly provider list for the "Configure LLM" screen.

catalog.py already exposes the FULL ~2,250-model LiteLLM catalogue for power
users / config JSON — this file is the small, demo-friendly layer on top:
"here are the providers LandIQ actually uses, here's what you need to plug
one in, and here's whether it's already configured." Mirrors the provider
picker UX pattern (curated list + required-credential fields), backed by
LandIQ's own working models and descriptions from model_catalogue.py.
"""

from typing import List, Optional
from src.utils.db import get_global_models

BASE_PROVIDERS = {
    "groq": {
        "name": "Groq",
        "logo": "🦙",
        "required_credentials": [
            {"key": "GROQ_API_KEY", "label": "Groq API Key", "placeholder": "gsk_..."}
        ],
        "default_models": ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b"],
        "description": "Free-tier, very fast inference. Primary provider for all LandIQ agents.",
    },
    "gemini": {
        "name": "Google Gemini",
        "logo": "⚡",
        "required_credentials": [
            {"key": "GOOGLE_API_KEY", "label": "Google API Key", "placeholder": "AI..."}
        ],
        "default_models": ["gemini/gemini-flash-latest", "gemini/gemini-2.5-pro"],
        "description": "Free-tier fallback. Large context window, good for RAG-heavy agents.",
    },
    "anthropic": {
        "name": "Anthropic",
        "logo": "🤖",
        "required_credentials": [
            {"key": "ANTHROPIC_API_KEY", "label": "Anthropic API Key", "placeholder": "sk-ant-..."}
        ],
        "default_models": ["anthropic/claude-sonnet-4-5-20250929"],
        "description": "Highest quality reasoning. Optional paid upgrade for legal/financial agents.",
    },
    "openai": {
        "name": "OpenAI",
        "logo": "🧠",
        "required_credentials": [
            {"key": "OPENAI_API_KEY", "label": "OpenAI API Key", "placeholder": "sk-..."}
        ],
        "default_models": ["openai/gpt-4o", "openai/gpt-4o-mini"],
        "description": "Industry-standard multimodal model. Optional paid upgrade.",
    },
    "mistral": {
        "name": "Mistral AI",
        "logo": "🔀",
        "required_credentials": [
            {"key": "MISTRAL_API_KEY", "label": "Mistral API Key", "placeholder": "..."}
        ],
        "default_models": ["mistral/mistral-large-latest"],
        "description": "Optional paid provider for structured analysis tasks.",
    },
    "deepseek": {
        "name": "DeepSeek",
        "logo": "🔍",
        "required_credentials": [
            {"key": "DEEPSEEK_API_KEY", "label": "DeepSeek API Key", "placeholder": "..."}
        ],
        "default_models": ["deepseek/deepseek-r1"],
        "description": "Optional paid provider — strong at ROI/financial math.",
    },
}


def get_curated_providers() -> List[dict]:
    """Curated provider list with live is_configured status from the pool."""
    pool = get_global_models()
    configured_providers = {m["provider"] for m in pool if m.get("has_api_key")}

    out = []
    for provider_id, info in BASE_PROVIDERS.items():
        out.append({
            "id": provider_id,
            "name": info["name"],
            "logo": info["logo"],
            "description": info["description"],
            "required_credentials": info["required_credentials"],
            "default_models": info["default_models"],
            "is_configured": provider_id in configured_providers,
        })
    return out


def get_provider(provider_id: str) -> Optional[dict]:
    info = BASE_PROVIDERS.get(provider_id)
    if not info:
        return None
    pool = get_global_models()
    configured = any(
        m.get("has_api_key") for m in pool if m.get("provider") == provider_id
    )
    return {
        "id": provider_id,
        "name": info["name"],
        "logo": info["logo"],
        "description": info["description"],
        "required_credentials": info["required_credentials"],
        "default_models": info["default_models"],
        "is_configured": configured,
    }
