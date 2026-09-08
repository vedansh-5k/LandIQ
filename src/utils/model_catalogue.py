"""
model_catalogue.py
------------------
Step 4 — Model Catalogue (sir's requirement).
Returns rich metadata for every model LandIQ supports.
Called by GET /catalogue endpoint in api.py.

WHY THIS FILE EXISTS:
Sir wants a professional Model Catalogue page, not a flat dropdown.
Each model needs metadata: provider, context window, speed, cost, capabilities.
This file is the single source of truth for all that metadata.
"""

import os
from typing import List, Dict, Optional
from pydantic import BaseModel


class ModelMeta(BaseModel):
    id: str
    name: str
    provider: str
    provider_logo: str          # emoji used as icon in frontend
    model_string: str           # exact string passed to LangChain
    context_window: int         # max input tokens
    max_output_tokens: int
    speed: str                  # "Fast" / "Medium" / "Slow"
    cost_tier: str              # "Free" / "Low" / "Medium" / "High"
    cost_per_1k_tokens: float   # USD per 1k tokens (0 = free)
    status: str                 # "available" / "requires_key"
    free: bool
    default_temperature: float
    capabilities: List[str]
    description: str
    strengths: List[str]
    best_for: str               # which LandIQ agents it suits best
    fallback_to: Optional[str]  # if this model fails, switch to


# ── THE CATALOGUE ──────────────────────────────────────────────────
# Add or remove models here. Nothing else needs to change.

CATALOGUE: List[ModelMeta] = [
    ModelMeta(
        id="groq-llama",
        name="Groq Llama/GPT-OSS",
        provider="Groq",
        provider_logo="🦙",
        # Was a hardcoded "llama-3.3-70b-versatile" — Groq decommissioned that
        # model, causing 404s on every agent call. Reads GROQ_MODEL the same
        # way src/utils/llm_configurator.py does now, so this display-only
        # catalogue can't drift from the live model again.
        model_string=os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        context_window=128000,
        max_output_tokens=32768,
        speed="Fast",
        cost_tier="Free",
        cost_per_1k_tokens=0.0,
        status="available",
        free=True,
        default_temperature=0.3,
        capabilities=["text", "reasoning", "structured_output", "multilingual"],
        description="Meta's flagship open model. Fast inference on Groq's LPU hardware. Best all-round free option.",
        strengths=["Very fast", "Strong reasoning", "100k context", "Zero cost"],
        best_for="All 8 agents — recommended default for demo",
        fallback_to=None
    ),
    ModelMeta(
        id="groq-mixtral",
        name="Mixtral 8x7B",
        provider="Groq",
        provider_logo="🔀",
        model_string="mixtral-8x7b-32768",
        context_window=32768,
        max_output_tokens=32768,
        speed="Fast",
        cost_tier="Free",
        cost_per_1k_tokens=0.0,
        status="available",
        free=True,
        default_temperature=0.3,
        capabilities=["text", "reasoning", "structured_output", "multilingual"],
        description="Mistral's mixture-of-experts architecture. Excellent for structured analysis tasks.",
        strengths=["Fast", "Good reasoning", "Free", "32k context"],
        best_for="Legal, Financial, Due Diligence agents",
        fallback_to="groq-llama"
    ),
    ModelMeta(
        id="groq-gemma",
        name="Gemma 2 9B",
        provider="Groq",
        provider_logo="💎",
        model_string="gemma2-9b-it",
        context_window=8192,
        max_output_tokens=8192,
        speed="Very Fast",
        cost_tier="Free",
        cost_per_1k_tokens=0.0,
        status="available",
        free=True,
        default_temperature=0.3,
        capabilities=["text", "reasoning", "structured_output"],
        description="Google's lightweight Gemma 2. Smallest and fastest free model. Good for simple tasks.",
        strengths=["Fastest", "Free", "Lightweight"],
        best_for="Market, Location agents (quick analysis)",
        fallback_to="groq-llama"
    ),
    ModelMeta(
        id="gemini-flash",
        name="Gemini 1.5 Flash",
        provider="Google",
        provider_logo="⚡",
        model_string="gemini-1.5-flash",
        context_window=1000000,
        max_output_tokens=8192,
        speed="Fast",
        cost_tier="Free",
        cost_per_1k_tokens=0.0,
        status="available",
        free=True,
        default_temperature=0.3,
        capabilities=["text", "reasoning", "structured_output", "vision", "multilingual", "long_context"],
        description="Google's fastest Gemini model. 1 million token context. Excellent for RAG-heavy tasks.",
        strengths=["1M context window", "Vision capable", "Free tier", "Fast"],
        best_for="All agents — especially RAG-heavy Location and Market agents",
        fallback_to="groq-llama"
    ),
    ModelMeta(
        id="gemini-pro",
        name="Gemini 1.5 Pro",
        provider="Google",
        provider_logo="🟢",
        model_string="gemini-1.5-pro",
        context_window=2000000,
        max_output_tokens=8192,
        speed="Medium",
        cost_tier="Free",
        cost_per_1k_tokens=0.0,
        status="available",
        free=True,
        default_temperature=0.3,
        capabilities=["text", "reasoning", "structured_output", "vision", "multilingual", "long_context"],
        description="Google's most capable Gemini model. 2M token context — largest available. Best for complex analysis.",
        strengths=["2M context", "Highest capability", "Vision", "Free tier"],
        best_for="Senior Consultant, Due Diligence — complex synthesis tasks",
        fallback_to="gemini-flash"
    ),
    ModelMeta(
        id="claude-sonnet",
        name="Claude 3.5 Sonnet",
        provider="Anthropic",
        provider_logo="🤖",
        model_string="claude-3-5-sonnet-20241022",
        context_window=200000,
        max_output_tokens=8192,
        speed="Medium",
        cost_tier="Medium",
        cost_per_1k_tokens=0.003,
        status="requires_key",
        free=False,
        default_temperature=0.3,
        capabilities=["text", "reasoning", "structured_output", "code", "multilingual", "analysis"],
        description="Anthropic's best model for complex reasoning. Top performance on legal and financial analysis.",
        strengths=["Best reasoning quality", "Excellent structured output", "200k context", "Nuanced analysis"],
        best_for="Legal, Financial, Senior Consultant — highest quality outputs",
        fallback_to="groq-llama"
    ),
    ModelMeta(
        id="gpt-4o",
        name="GPT-4o",
        provider="OpenAI",
        provider_logo="🧠",
        model_string="gpt-4o",
        context_window=128000,
        max_output_tokens=16384,
        speed="Medium",
        cost_tier="High",
        cost_per_1k_tokens=0.005,
        status="requires_key",
        free=False,
        default_temperature=0.3,
        capabilities=["text", "reasoning", "structured_output", "vision", "code", "multilingual"],
        description="OpenAI's flagship multimodal model. Industry benchmark for reasoning and structured output.",
        strengths=["Industry standard", "Vision capable", "Strong structured output", "Well-tested"],
        best_for="All agents — production deployments where quality is priority",
        fallback_to="claude-sonnet"
    ),
    ModelMeta(
        id="deepseek-r1",
        name="DeepSeek R1",
        provider="DeepSeek",
        provider_logo="🔍",
        model_string="deepseek/deepseek-r1",
        context_window=64000,
        max_output_tokens=8000,
        speed="Slow",
        cost_tier="Low",
        cost_per_1k_tokens=0.0005,
        status="requires_key",
        free=False,
        default_temperature=0.1,
        capabilities=["text", "reasoning", "structured_output", "math", "code"],
        description="DeepSeek's reasoning model. Exceptional for complex mathematical and financial calculations.",
        strengths=["Strong math/logic", "Very cheap", "Chain-of-thought reasoning"],
        best_for="Financial ROI agent — complex ROI calculations",
        fallback_to="groq-llama"
    ),
]

# ── CATALOGUE LOOKUP FUNCTIONS ────────────────────────────────────

_by_id: Dict[str, ModelMeta] = {m.id: m for m in CATALOGUE}


def get_all_models() -> List[dict]:
    return [m.model_dump() for m in CATALOGUE]


def get_model_by_id(model_id: str) -> Optional[dict]:
    m = _by_id.get(model_id)
    return m.model_dump() if m else None


def get_models_by_provider(provider: str) -> List[dict]:
    return [m.model_dump() for m in CATALOGUE if m.provider.lower() == provider.lower()]


def get_free_models() -> List[dict]:
    return [m.model_dump() for m in CATALOGUE if m.free]


def get_fallback_id(model_id: str) -> Optional[str]:
    m = _by_id.get(model_id)
    return m.fallback_to if m else None