"""
agent_configurator.py
---------------------
Step 5 of sir's framework.
Per-agent settings — which LLM, temperature,
enabled/disabled, max tokens.
"""

_agent_config = {
    "location": {
        "enabled": True,
        "temperature": 0.3,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "description": "Analyses location, connectivity, infrastructure"
    },
    "legal": {
        "enabled": True,
        "temperature": 0.1,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "description": "Reviews title, legal risks, compliance"
    },
    "financial": {
        "enabled": True,
        "temperature": 0.2,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "description": "ROI, loan analysis, financial projections"
    },
    "market": {
        "enabled": True,
        "temperature": 0.4,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "description": "Market trends, demand, price forecasts"
    },
    "bull": {
        "enabled": True,
        "temperature": 0.5,
        "llm_id": "groq-llama",
        "max_tokens": 512,
        "description": "Investment advocate — best case analysis"
    },
    "bear": {
        "enabled": True,
        "temperature": 0.5,
        "llm_id": "groq-llama",
        "max_tokens": 512,
        "description": "Devil advocate — worst case risks"
    },
    "due_diligence": {
        "enabled": True,
        "temperature": 0.2,
        "llm_id": "groq-llama",
        "max_tokens": 1024,
        "description": "Fact-checks all agents, resolves conflicts"
    },
    "senior_consultant": {
        "enabled": True,
        "temperature": 0.3,
        "llm_id": "groq-llama",
        "max_tokens": 2048,
        "description": "Final recommendation synthesis"
    }
}


def get_agent_config(agent_name: str) -> dict:
    return _agent_config.get(agent_name, {
        "enabled": True,
        "temperature": 0.3,
        "llm_id": "groq-llama",
        "max_tokens": 1024
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


def get_enabled_agents() -> list:
    return [k for k, v in _agent_config.items() if v["enabled"]]


def get_status() -> dict:
    return _agent_config