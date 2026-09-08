"""
agent_configurator.py
---------------------
Step 5 of sir's framework.
Per-agent settings — which LLM, temperature,
enabled/disabled, max tokens.
"""

import sys

# See toon.py for why: cp1252 Windows consoles can't print the → below and
# that crash was getting swallowed by callers' broad except blocks.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

_agent_config = {
    "location": {
        "enabled": True,
        "temperature": 0.3,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "config_full_name": None,
        "description": "Analyses location, connectivity, infrastructure"
    },
    "legal": {
        "enabled": True,
        "temperature": 0.1,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "config_full_name": None,
        "description": "Reviews title, legal risks, compliance"
    },
    "financial": {
        "enabled": True,
        "temperature": 0.2,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "config_full_name": None,
        "description": "ROI, loan analysis, financial projections"
    },
    "market": {
        "enabled": True,
        "temperature": 0.4,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "config_full_name": None,
        "description": "Market trends, demand, price forecasts"
    },
    "bull": {
        "enabled": True,
        "temperature": 0.5,
        "llm_id": "groq-llama",
        "max_tokens": 512,
        "config_full_name": None,
        "description": "Investment advocate — best case analysis"
    },
    "bear": {
        "enabled": True,
        "temperature": 0.5,
        "llm_id": "groq-llama",
        "max_tokens": 512,
        "config_full_name": None,
        "description": "Devil advocate — worst case risks"
    },
    "due_diligence": {
        "enabled": True,
        "temperature": 0.2,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "config_full_name": None,
        "description": "Fact-checks all agents, resolves conflicts"
    },
    "senior_consultant": {
        "enabled": True,
        "temperature": 0.3,
        "llm_id": "groq-llama",
        "max_tokens": 2048,
        "config_full_name": None,
        "description": "Final recommendation synthesis"
    }
}


def get_agent_config(agent_name: str) -> dict:
    return _agent_config.get(agent_name, {
        "enabled": True,
        "temperature": 0.3,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "config_full_name": None
    })


def set_temperature(agent_name: str, temp: float):
    if agent_name in _agent_config:
        _agent_config[agent_name]["temperature"] = round(temp, 2)
        print(f"  [AGENT CONFIG] {agent_name} temperature = {temp}")


def set_enabled(agent_name: str, enabled: bool):
    if agent_name in _agent_config:
        _agent_config[agent_name]["enabled"] = enabled
        print(f"  [AGENT CONFIG] {agent_name} enabled = {enabled}")


def set_llm(agent_name: str, llm_id: str):
    if agent_name in _agent_config:
        _agent_config[agent_name]["llm_id"] = llm_id
        print(f"  [AGENT CONFIG] {agent_name} → {llm_id}")


def set_config_full_name(agent_name: str, full_name):
    """Bind an agent to a named LLM config (Config 2 -> Config 1, System B).
    Pass full_name=None to clear the binding and revert the agent to its
    normal fallback chain."""
    if agent_name in _agent_config:
        _agent_config[agent_name]["config_full_name"] = full_name
        print(f"  [AGENT CONFIG] {agent_name} config_full_name = {full_name}")


def get_enabled_agents() -> list:
    return [k for k, v in _agent_config.items() if v["enabled"]]


def get_status() -> dict:
    return _agent_config