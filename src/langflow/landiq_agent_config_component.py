"""
landiq_agent_config_component.py — "LandIQ Agent Config" Langflow box (Config 2)
-----------------------------------------------------------------------------
PASTE THIS WHOLE FILE into a new Custom Component in Langflow's UI.
See the numbered steps Claude gave you in chat for exactly how.

WHAT THIS BOX IS:
This is Config 2 that sir asked for — the agent-level config. Pick an agent
from the dropdown (read live from agents_registry/ — nothing hardcoded, add
a new agent folder and it shows up here automatically), pick which Config 1
it should use (defaults to landiq_model), hit Run.

What actually happens when you run it:
  1. It tells the backend "this agent now uses this config" — a REAL,
     persistent setting (POST /agent-config/{agent}/set-llm-config). This is
     not just a one-off test — from this point on, that agent uses this
     config every time it runs anywhere in LandIQ, until you change or clear
     it, exactly like sir described ("agent uses config 1 directly").
  2. It then runs that agent once, for real, on a sample property, so you
     can see the config-2-> config-1 chain working end to end right here in
     the Playground ("test board").

Follows the same house style as your existing "Orchestrator LLM" and
"PII Safety Guardrail" boxes: a thin wrapper that calls the backend and
returns the result. No new backend logic lives here — it only calls the two
new /agent-config endpoints and the existing /run-single-agent endpoint.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output
from lfx.schema.message import Message
import json
import os

BACKEND_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = r"C:\Users\HP\OneDrive\Desktop\ai_boardroom_v3"
AGENTS_DIR = os.path.join(PROJECT_ROOT, "agents_registry")

_FALLBACK_AGENTS = [
    "location", "legal", "financial", "market",
    "bull", "bear", "due_diligence", "senior_consultant",
]


def _discover_agents():
    """Only folders that actually contain an agent definition file count —
    plain os.path.isdir also matches __pycache__ and other non-agent
    folders that can appear under agents_registry/."""
    try:
        names = []
        for folder in sorted(os.listdir(AGENTS_DIR)):
            folder_path = os.path.join(AGENTS_DIR, folder)
            if not os.path.isdir(folder_path):
                continue
            has_agent_file = any(
                os.path.isfile(os.path.join(folder_path, fname))
                for fname in ("AGENT.md", "AGENT.txt", f"{folder}.md", f"{folder}.txt")
            )
            if has_agent_file:
                names.append(folder)
        return names or list(_FALLBACK_AGENTS)
    except Exception:
        return list(_FALLBACK_AGENTS)


_AGENT_NAMES = _discover_agents()

_DEFAULT_PROPERTY_JSON = (
    '{"area":"Whitefield","city":"Bangalore","state":"Karnataka",'
    '"land_size":"1000","land_unit":"sqft","total_budget":"5000000",'
    '"purpose":"residential"}'
)


class LandIQAgentConfig(Component):
    display_name = "LandIQ Agent Config"
    description = (
        "Config 2 — binds one agent (read live from agents_registry/, "
        "nothing hardcoded) to a Config-1 LLM config such as landiq_model. "
        "The binding is real and persists: after this runs, that agent uses "
        "the chosen config every time it runs, not just here. Also runs "
        "the agent once immediately so you can see it working."
    )
    icon = "user-cog"
    name = "LandIQAgentConfig"

    inputs = [
        DropdownInput(
            name="agent_name",
            display_name="Agent",
            options=_AGENT_NAMES,
            value=_AGENT_NAMES[0] if _AGENT_NAMES else "",
            info="Which agent (from agents_registry/) this config applies to.",
        ),
        MessageTextInput(
            name="config_full_name",
            display_name="LLM Config Name",
            value="landiq_model",
            info="Which Config-1 this agent should use.",
        ),
        MessageTextInput(
            name="property_json",
            display_name="Test Property (JSON)",
            value=_DEFAULT_PROPERTY_JSON,
            info="Sample property data used only to test-run the agent here.",
        ),
    ]

    outputs = [
        Output(display_name="Agent Output", name="agent_output", method="run_bound_agent"),
    ]

    def run_bound_agent(self) -> Message:
        import httpx

        agent_name = (self.agent_name or "").strip()
        full_name = (self.config_full_name or "landiq_model").strip()

        if not agent_name:
            return Message(text="[error] No agent selected.")

        try:
            bind = httpx.post(
                f"{BACKEND_URL}/agent-config/{agent_name}/set-llm-config",
                json={"full_name": full_name},
                timeout=15,
            )
            bind_data = bind.json() if bind.status_code == 200 else None
            if not bind_data:
                msg = f"[bind failed] HTTP {bind.status_code}: {bind.text[:200]}"
                self.status = msg
                return Message(text=msg)
        except Exception as e:
            msg = f"[bind error] {type(e).__name__}: {str(e)[:200]}"
            self.status = msg
            return Message(text=msg)

        try:
            state = json.loads(self.property_json or "{}")
        except Exception:
            state = {}

        try:
            r = httpx.post(
                f"{BACKEND_URL}/run-single-agent",
                json={"agent_name": agent_name, "state": state},
                timeout=120,
            )
            data = r.json()
        except Exception as e:
            msg = f"[agent run error] {type(e).__name__}: {str(e)[:200]}"
            self.status = msg
            return Message(text=msg)

        self.status = data
        if data.get("success"):
            result = data.get("result", {})
            out = result.get(f"{agent_name}_output", result)
            return Message(
                text=f"[{agent_name}] now bound to '{full_name}' — this run's result:\n\n"
                     f"{json.dumps(out, indent=2, default=str)}"
            )
        return Message(text=f"[agent run failed] {json.dumps(data)[:300]}")
