"""
llm_configurator.py
-------------------
Step 4 of sir's framework.
Manages which LLMs are available, their limits,
priority order, and auto-rotation when key exhausted.
"""

from langchain_groq import ChatGroq

_config = {
    "active_id": "groq-llama",
    "llms": [
        {
            "id": "groq-llama",
            "name": "Llama 3.3 70B",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": None,  # loaded from env
            "priority": 1,
            "enabled": True,
            "daily_limit": 100000,
            "used_today": 0,
            "output_format": "structured_json"
        },
        {
            "id": "groq-mixtral",
            "name": "Mixtral 8x7B",
            "provider": "groq",
            "model": "mixtral-8x7b-32768",
            "api_key": None,
            "priority": 2,
            "enabled": True,
            "daily_limit": 100000,
            "used_today": 0,
            "output_format": "structured_json"
        },
        {
            "id": "groq-gemma",
            "name": "Gemma 2 9B",
            "provider": "groq",
            "model": "gemma2-9b-it",
            "api_key": None,
            "priority": 3,
            "enabled": True,
            "daily_limit": 100000,
            "used_today": 0,
            "output_format": "structured_json"
        }
    ]
}


def _get_llm_by_id(llm_id: str):
    for llm in _config["llms"]:
        if llm["id"] == llm_id:
            return llm
    return None


def get_active_llm() -> dict:
    llm = _get_llm_by_id(_config["active_id"])
    if llm and llm["enabled"]:
        return llm
    return _rotate_to_next()


def set_active_llm(llm_id: str):
    llm = _get_llm_by_id(llm_id)
    if llm:
        _config["active_id"] = llm_id
        print(f"  [LLM CONFIG] Switched to: {llm['name']}")


def _rotate_to_next() -> dict:
    enabled = sorted(
        [l for l in _config["llms"] if l["enabled"]],
        key=lambda x: x["priority"]
    )
    if enabled:
        _config["active_id"] = enabled[0]["id"]
        print(f"  [LLM CONFIG] Auto-rotated to: {enabled[0]['name']}")
        return enabled[0]
    raise Exception("All LLMs exhausted. Wait for daily reset at 5:30 AM IST.")


def record_tokens(tokens_used: int):
    llm = get_active_llm()
    llm["used_today"] += tokens_used
    remaining = llm["daily_limit"] - llm["used_today"]
    print(f"  [LLM CONFIG] {llm['name']} — used {llm['used_today']}/{llm['daily_limit']} today")
    if remaining <= 500:
        print(f"  [LLM CONFIG] {llm['name']} limit almost reached — rotating")
        llm["enabled"] = False
        _rotate_to_next()


def update_restriction(llm_id: str, field: str, value):
    llm = _get_llm_by_id(llm_id)
    if llm and field in llm:
        llm[field] = value
        print(f"  [LLM CONFIG] {llm_id} {field} = {value}")


def reset_daily():
    for llm in _config["llms"]:
        llm["used_today"] = 0
        llm["enabled"] = True
    print("  [LLM CONFIG] Daily limits reset")


def get_langchain_llm(temperature: float = 0.3):
    """Returns a ready-to-use LangChain ChatGroq instance."""
    import os
    llm = get_active_llm()
    api_key = os.getenv("GROQ_API_KEY")
    return ChatGroq(
        api_key=api_key,
        model=llm["model"],
        temperature=temperature
    )


def get_status() -> dict:
    active = get_active_llm()
    return {
        "active_llm": active["name"],
        "active_model": active["model"],
        "llms": [
            {
                "id": l["id"],
                "name": l["name"],
                "model": l["model"],
                "priority": l["priority"],
                "enabled": l["enabled"],
                "used_today": l["used_today"],
                "daily_limit": l["daily_limit"],
                "remaining": l["daily_limit"] - l["used_today"]
            }
            for l in _config["llms"]
        ]
    }