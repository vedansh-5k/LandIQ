"""
litellm_config.py — FIXED FINAL
Uses original simple model IDs (groq-llama-3.3-70b format) that 
match the frontend, api.py, and all existing code.
Additional providers added without breaking anything.
"""

import os

AVAILABLE_MODELS = {

    # ══ GROQ — FREE ══════════════════════════════════════════
    "groq-llama-3.3-70b": {
        "id": "groq-llama-3.3-70b",
        "name": "Llama 3.3 70B",
        "provider": "Groq",
        "litellm_model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
        "free": True,
        "description": "Best free model — recommended"
    },
    "groq-llama-3.1-8b": {
        "id": "groq-llama-3.1-8b",
        "name": "Llama 3.1 8B",
        "provider": "Groq",
        "litellm_model": "llama-3.1-8b-instant",
        "api_key_env": "GROQ_API_KEY",
        "free": True,
        "description": "Fastest free model"
    },
    "groq-mixtral": {
        "id": "groq-mixtral",
        "name": "Mixtral 8x7B",
        "provider": "Groq",
        "litellm_model": "mixtral-8x7b-32768",
        "api_key_env": "GROQ_API_KEY",
        "free": True,
        "description": "Large context free"
    },
    "groq-gemma": {
        "id": "groq-gemma",
        "name": "Gemma 2 9B",
        "provider": "Groq",
        "litellm_model": "gemma2-9b-it",
        "api_key_env": "GROQ_API_KEY",
        "free": True,
        "description": "Google Gemma on Groq"
    },

    # ══ GOOGLE GEMINI — FREE ══════════════════════════════════
    "gemini-1.5-flash": {
        "id": "gemini-1.5-flash",
        "name": "Gemini 1.5 Flash",
        "provider": "Google",
        "litellm_model": "gemini-1.5-flash",
        "api_key_env": "GOOGLE_API_KEY",
        "free": True,
        "description": "Fast free Gemini"
    },
    "gemini-1.5-pro": {
        "id": "gemini-1.5-pro",
        "name": "Gemini 1.5 Pro",
        "provider": "Google",
        "litellm_model": "gemini-1.5-pro",
        "api_key_env": "GOOGLE_API_KEY",
        "free": True,
        "description": "Most capable free Gemini"
    },
    "gemini-2.0-flash": {
        "id": "gemini-2.0-flash",
        "name": "Gemini 2.0 Flash",
        "provider": "Google",
        "litellm_model": "gemini-2.0-flash",
        "api_key_env": "GOOGLE_API_KEY",
        "free": True,
        "description": "Newest Gemini"
    },
    "gemini-1.5-flash-8b": {
        "id": "gemini-1.5-flash-8b",
        "name": "Gemini Flash 8B",
        "provider": "Google",
        "litellm_model": "gemini-1.5-flash-8b",
        "api_key_env": "GOOGLE_API_KEY",
        "free": True,
        "description": "Lightest Gemini"
    },

    # ══ ANTHROPIC — PAID ══════════════════════════════════════
    "claude-3.5-sonnet": {
        "id": "claude-3.5-sonnet",
        "name": "Claude 3.5 Sonnet",
        "provider": "Anthropic",
        "litellm_model": "claude-3-5-sonnet-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",
        "free": False,
        "description": "Best Claude — needs credits"
    },
    "claude-3.5-haiku": {
        "id": "claude-3.5-haiku",
        "name": "Claude 3.5 Haiku",
        "provider": "Anthropic",
        "litellm_model": "claude-3-5-haiku-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",
        "free": False,
        "description": "Fast Claude"
    },
    "claude-3-haiku": {
        "id": "claude-3-haiku",
        "name": "Claude 3 Haiku",
        "provider": "Anthropic",
        "litellm_model": "claude-3-haiku-20240307",
        "api_key_env": "ANTHROPIC_API_KEY",
        "free": False,
        "description": "Cheapest Claude"
    },

    # ══ OPENAI — PAID ═════════════════════════════════════════
    "gpt-4o": {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "OpenAI",
        "litellm_model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
        "free": False,
        "description": "OpenAI flagship"
    },
    "gpt-4o-mini": {
        "id": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider": "OpenAI",
        "litellm_model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "free": False,
        "description": "Fast affordable GPT"
    },
    "gpt-4-turbo": {
        "id": "gpt-4-turbo",
        "name": "GPT-4 Turbo",
        "provider": "OpenAI",
        "litellm_model": "gpt-4-turbo",
        "api_key_env": "OPENAI_API_KEY",
        "free": False,
        "description": "GPT-4 Turbo"
    },

    # ══ MISTRAL — PAID ════════════════════════════════════════
    "mistral-large": {
        "id": "mistral-large",
        "name": "Mistral Large",
        "provider": "Mistral",
        "litellm_model": "mistral-large-latest",
        "api_key_env": "MISTRAL_API_KEY",
        "free": False,
        "description": "Mistral flagship"
    },
    "mistral-small": {
        "id": "mistral-small",
        "name": "Mistral Small",
        "provider": "Mistral",
        "litellm_model": "mistral-small-latest",
        "api_key_env": "MISTRAL_API_KEY",
        "free": False,
        "description": "Fast Mistral"
    },

    # ══ DEEPSEEK — PAID ═══════════════════════════════════════
    "deepseek-chat": {
        "id": "deepseek-chat",
        "name": "DeepSeek V3",
        "provider": "DeepSeek",
        "litellm_model": "deepseek/deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "free": False,
        "description": "DeepSeek V3 — very affordable"
    },
    "deepseek-r1": {
        "id": "deepseek-r1",
        "name": "DeepSeek R1",
        "provider": "DeepSeek",
        "litellm_model": "deepseek/deepseek-reasoner",
        "api_key_env": "DEEPSEEK_API_KEY",
        "free": False,
        "description": "DeepSeek reasoning model"
    },

    # ══ COHERE — PAID ═════════════════════════════════════════
    "cohere-command-r-plus": {
        "id": "cohere-command-r-plus",
        "name": "Command R+",
        "provider": "Cohere",
        "litellm_model": "cohere/command-r-plus",
        "api_key_env": "COHERE_API_KEY",
        "free": False,
        "description": "Cohere RAG-optimized"
    },
    "cohere-command-r": {
        "id": "cohere-command-r",
        "name": "Command R",
        "provider": "Cohere",
        "litellm_model": "cohere/command-r",
        "api_key_env": "COHERE_API_KEY",
        "free": False,
        "description": "Cohere fast model"
    },

    # ══ PERPLEXITY — PAID ═════════════════════════════════════
    "perplexity-sonar-large": {
        "id": "perplexity-sonar-large",
        "name": "Sonar Large (Online)",
        "provider": "Perplexity",
        "litellm_model": "perplexity/llama-3.1-sonar-large-128k-online",
        "api_key_env": "PERPLEXITYAI_API_KEY",
        "free": False,
        "description": "Web-connected Perplexity"
    },

    # ══ TOGETHER AI — PAID ════════════════════════════════════
    "together-llama-3-70b": {
        "id": "together-llama-3-70b",
        "name": "Llama 3 70B (Together)",
        "provider": "TogetherAI",
        "litellm_model": "together_ai/meta-llama/Llama-3-70b-chat-hf",
        "api_key_env": "TOGETHERAI_API_KEY",
        "free": False,
        "description": "Meta Llama 3 via Together AI"
    },
    "together-mixtral": {
        "id": "together-mixtral",
        "name": "Mixtral (Together)",
        "provider": "TogetherAI",
        "litellm_model": "together_ai/mistralai/Mixtral-8x7B-Instruct-v0.1",
        "api_key_env": "TOGETHERAI_API_KEY",
        "free": False,
        "description": "Mixtral via Together AI"
    },
}

# ── Provider → env var map for BYOK (any custom model) ───────────────────────
PROVIDER_KEY_MAP = {
    "Groq": "GROQ_API_KEY",
    "Google": "GOOGLE_API_KEY",
    "Anthropic": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "Mistral": "MISTRAL_API_KEY",
    "Cohere": "COHERE_API_KEY",
    "DeepSeek": "DEEPSEEK_API_KEY",
    "Perplexity": "PERPLEXITYAI_API_KEY",
    "TogetherAI": "TOGETHERAI_API_KEY",
    "Replicate": "REPLICATE_API_KEY",
}

_active_model_id = "groq-llama-3.3-70b"


def set_active_model(model_id: str) -> bool:
    global _active_model_id
    if model_id in AVAILABLE_MODELS:
        _active_model_id = model_id
        m = AVAILABLE_MODELS[model_id]
        print(f"  [LITELLM] Active model set to: {m['name']} ({m['provider']})")
        return True
    # Dynamic custom model — register on the fly
    provider = _detect_provider(model_id)
    AVAILABLE_MODELS[model_id] = {
        "id": model_id,
        "name": model_id,
        "provider": provider,
        "litellm_model": model_id,
        "api_key_env": PROVIDER_KEY_MAP.get(provider, "CUSTOM_API_KEY"),
        "free": False,
        "description": f"Custom — {provider}"
    }
    _active_model_id = model_id
    print(f"  [LITELLM] Dynamic model: {model_id} ({provider})")
    return True


def _detect_provider(model_id: str) -> str:
    mid = model_id.lower()
    if "groq" in mid:           return "Groq"
    if "gemini" in mid:         return "Google"
    if "claude" in mid:         return "Anthropic"
    if "gpt" in mid:            return "OpenAI"
    if "mistral" in mid:        return "Mistral"
    if "deepseek" in mid:       return "DeepSeek"
    if "cohere" in mid:         return "Cohere"
    if "together" in mid:       return "TogetherAI"
    if "perplexity" in mid:     return "Perplexity"
    if "llama" in mid:          return "Groq"
    return "Custom"


def get_active_model() -> dict:
    return AVAILABLE_MODELS.get(_active_model_id, AVAILABLE_MODELS["groq-llama-3.3-70b"])


def get_active_model_id() -> str:
    return _active_model_id


def get_available_models_list() -> list:
    result = []
    for mid, m in AVAILABLE_MODELS.items():
        available = bool(os.getenv(m["api_key_env"], ""))
        result.append({**m, "available": available, "active": mid == _active_model_id})
    return result