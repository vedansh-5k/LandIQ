"""
model_router.py
---------------
Intelligent model routing with automatic fallback.
Adapted from the student's router_manager.py concept.

HOW IT WORKS:
1. Agent calls get_llm_for_agent() in llm_factory.py
2. Factory calls model_router.resolve(model_id)
3. Router checks: is primary model over its token threshold?
4. If YES  -> returns the fallback model id
5. If NO   -> returns the primary model id
6. Factory creates the LangChain object for whichever id was returned
7. After the run, factory calls router.record_usage() to track tokens

WHY THIS PATTERN:
- Agents never know which model was used. They get a LangChain object.
- No changes needed in agents, tracked_chain, or orchestrator.
- The entire intelligence lives here and in llm_factory.py only.

ADAPTED FROM: student's router_manager.py (priority + fallback concept)
DIFFERENCES: No LiteLLM Router object (we use LangChain classes directly),
no SQLite, no async, simplified to what LandIQ actually needs.
"""

import os
from typing import Optional
from src.utils.rate_limiter import rate_limiter
from src.utils.model_catalogue import get_fallback_id, get_model_by_id

# Tracks which model was actually used per agent in the current run
# Format: {agent_name: model_id}
_actual_models_used: dict = {}

# Token threshold config (per model, in tokens)
# 0 = no threshold (never auto-switch based on tokens)
# Set via POST /models/set-threshold in api.py
_thresholds: dict = {}


def configure_threshold(model_id: str, max_tokens: int):
    """
    Set the token threshold for a model.
    Example: configure_threshold("gemini-flash", 10000)
    After 10,000 tokens on Gemini, it auto-switches to Gemini's fallback.
    """
    _thresholds[model_id] = max_tokens
    rate_limiter.set_threshold(model_id, max_tokens)
    print(f"  [ROUTER] Threshold set: {model_id} -> {max_tokens} tokens")


def resolve(primary_model_id: str, agent_name: str) -> str:
    """
    Given a primary model id, returns the model id that should actually be used.
    If primary is over threshold -> returns fallback model id.
    If primary is fine -> returns primary model id.
    Also records which model was chosen for this agent.
    """
    # Check token threshold
    if rate_limiter.is_threshold_exceeded(primary_model_id):
        fallback_id = get_fallback_id(primary_model_id)
        if fallback_id:
            print(f"  [ROUTER] {primary_model_id} threshold exceeded -> switching to {fallback_id} for {agent_name}")
            _actual_models_used[agent_name] = fallback_id
            return fallback_id
        else:
            print(f"  [ROUTER] {primary_model_id} threshold exceeded but no fallback configured")

    _actual_models_used[agent_name] = primary_model_id
    return primary_model_id


def record_usage(model_id: str, tokens_used: int):
    """
    Call this after each agent run to track token consumption.
    The rate_limiter uses this to decide future switching.
    """
    rate_limiter.record_tokens(model_id, tokens_used)
    rate_limiter.record_request(model_id)


def get_routing_report() -> dict:
    """
    Returns which model each agent actually used in the last run.
    Included in /analyse response so frontend can show it.
    """
    return dict(_actual_models_used)


def get_usage_report() -> dict:
    """Returns current token + RPM usage per model."""
    from src.utils.model_catalogue import CATALOGUE
    report = {}
    for m in CATALOGUE:
        report[m.id] = rate_limiter.get_usage(m.id)
    return report


def reset_session():
    """Call at the start of each /analyse request to reset per-session tracking."""
    _actual_models_used.clear()
    rate_limiter.reset_session()