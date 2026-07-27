"""
llm_configurator.py — UPDATED (adds fallback_to field)
-------------------------------------------------------
Step 4 of sir's framework.
Registers LLMs with provider, limits, and fallback chain.

WHAT CHANGED FROM PREVIOUS VERSION:
- Added fallback_to field to each model entry
- Added get_fallback() function
- Added set_fallback() function (used by new API endpoint)
- Everything else identical — existing calls still work

NOTHING BREAKS:
- get_active_llm() same signature
- set_active_llm() same signature
- get_status() same signature
- All existing api.py routes still work
"""

_config = {
    "active_id": "groq-llama",
    "llms": [
        {
            "id": "groq-llama",
            "name": "Llama 3.3 70B",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "priority": 1,
            "enabled": True,
            "daily_limit": 100000,
            "used_today": 0,
            "free": True,
            "fallback_to": None          # highest priority — no fallback
        },
        {
            "id": "groq-mixtral",
            "name": "Mixtral 8x7B",
            "provider": "groq",
            "model": "mixtral-8x7b-32768",
            "priority": 2,
            "enabled": True,
            "daily_limit": 100000,
            "used_today": 0,
            "free": True,
            "fallback_to": "groq-llama"
        },
        {
            "id": "groq-gemma",
            "name": "Gemma 2 9B",
            "provider": "groq",
            "model": "gemma2-9b-it",
            "priority": 3,
            "enabled": True,
            "daily_limit": 100000,
            "used_today": 0,
            "free": True,
            "fallback_to": "groq-llama"
        },
        {
            "id": "gemini-flash",
            "name": "Gemini 1.5 Flash",
            "provider": "google",
            "model": "gemini-1.5-flash",
            "priority": 4,
            "enabled": True,
            "daily_limit": 1000000,
            "used_today": 0,
            "free": True,
            "fallback_to": "groq-llama"  # if Gemini hits limit -> Groq Llama
        },
        {
            "id": "gemini-pro",
            "name": "Gemini 1.5 Pro",
            "provider": "google",
            "model": "gemini-1.5-pro",
            "priority": 5,
            "enabled": True,
            "daily_limit": 1000000,
            "used_today": 0,
            "free": True,
            "fallback_to": "gemini-flash"  # Pro -> Flash -> Llama
        },
        {
            "id": "claude-sonnet",
            "name": "Claude 3.5 Sonnet",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
            "priority": 6,
            "enabled": True,
            "daily_limit": 0,
            "used_today": 0,
            "free": False,
            "fallback_to": "groq-llama"
        },
        {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "provider": "openai",
            "model": "gpt-4o",
            "priority": 7,
            "enabled": True,
            "daily_limit": 0,
            "used_today": 0,
            "free": False,
            "fallback_to": "claude-sonnet"
        },
        {
            "id": "deepseek-r1",
            "name": "DeepSeek R1",
            "provider": "deepseek",
            "model": "deepseek/deepseek-r1",
            "priority": 8,
            "enabled": True,
            "daily_limit": 0,
            "used_today": 0,
            "free": False,
            "fallback_to": "groq-llama"
        },
    ]
}


def _by_id(i):
    for l in _config["llms"]:
        if l["id"] == i:
            return l
    return None


def get_active_llm():
    l = _by_id(_config["active_id"])
    if l and l["enabled"]:
        return l
    # auto-rotate to next priority if active is disabled
    enabled = sorted([x for x in _config["llms"] if x["enabled"]], key=lambda x: x["priority"])
    if enabled:
        _config["active_id"] = enabled[0]["id"]
        return enabled[0]
    raise Exception("No enabled LLMs configured")


def set_active_llm(llm_id: str) -> bool:
    l = _by_id(llm_id)
    if l:
        _config["active_id"] = llm_id
        print(f"  [LLM CONFIG] Switched to: {l['name']}")
        return True
    return False


def get_fallback(llm_id: str):
    """Returns the fallback model entry for a given model id, or None."""
    l = _by_id(llm_id)
    if not l or not l.get("fallback_to"):
        return None
    return _by_id(l["fallback_to"])


def set_fallback(llm_id: str, fallback_id: str) -> bool:
    """Configure which model to fall back to when llm_id hits its threshold."""
    l = _by_id(llm_id)
    fb = _by_id(fallback_id)
    if l and fb:
        l["fallback_to"] = fallback_id
        print(f"  [LLM CONFIG] Fallback set: {l['name']} -> {fb['name']}")
        return True
    return False


def update_restriction(llm_id: str, field: str, value):
    l = _by_id(llm_id)
    if l and field in l:
        l[field] = value


def reset_daily():
    for l in _config["llms"]:
        l["used_today"] = 0
        l["enabled"] = True


def get_status():
    a = get_active_llm()
    return {
        "active_llm": a["name"],
        "active_model": a["model"],
        "active_provider": a["provider"],
        "active_fallback": a.get("fallback_to"),
        "llms": [
            {
                "id": l["id"],
                "name": l["name"],
                "provider": l["provider"],
                "model": l["model"],
                "priority": l["priority"],
                "enabled": l["enabled"],
                "free": l["free"],
                "used_today": l["used_today"],
                "daily_limit": l["daily_limit"],
                "fallback_to": l.get("fallback_to")
            }
            for l in _config["llms"]
        ]
    }