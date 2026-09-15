"""
landiq_config_agent_component.py — "LandIQ Config Agent" Langflow box (Config 2, new)
-----------------------------------------------------------------------------
A NEW, separate box — the original "LandIQ Agent Config" box stays exactly
as it is on the canvas. This one binds an agent to whatever "LandIQ
Config Picker" sends it — either one of your saved website configs, or a
different client's own bring-your-own model — through a single wire.

Both backend mechanisms this box calls already existed and were already
tested working before this box was written:
  - Saved config path: POST /agent-config/{agent}/set-llm-config (binds
    the agent to that config_full_name — the exact same endpoint the
    earlier "bull -> landiq_model" test used) then runs the agent
    normally; agent_configurator.py's binding is what actually makes it
    use that config.
  - Custom path: sends llm_model_override / llm_api_key_override
    directly (dynamic_agent.py's existing explicit-override mechanism —
    the same one the other Config-2 box already uses).
No new backend code was needed for either path.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, DataInput, MessageTextInput, Output
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


class LandIQConfigAgent(Component):
    display_name = "LandIQ Config Agent"
    description = (
        "Config 2 — binds one agent (read live from agents_registry/, "
        "nothing hardcoded) to whatever 'LandIQ Config Picker' sends it — "
        "a saved LandIQ website config, or a different client's own "
        "bring-your-own model. One wire, real backend calls, no config "
        "name guessing."
    )
    icon = "user-cog"
    name = "LandIQConfigAgent"

    inputs = [
        DropdownInput(
            name="agent_name",
            display_name="Agent",
            options=_AGENT_NAMES,
            value=_AGENT_NAMES[0] if _AGENT_NAMES else "",
            info="Which agent (from agents_registry/) this config applies to.",
        ),
        DataInput(
            name="model_config",
            display_name="Model",
            info="Wire in 'LandIQ Config Picker'’s Model Config output.",
        ),
        MessageTextInput(
            name="property_json",
            display_name="Test Property (JSON)",
            value=_DEFAULT_PROPERTY_JSON,
            info="Sample property data used to test-run the agent here.",
        ),
    ]

    outputs = [
        Output(display_name="Agent Output", name="agent_output", method="run_bound_agent"),
    ]

    def run_bound_agent(self) -> Message:
        import httpx

        agent_name = (self.agent_name or "").strip()
        if not agent_name:
            return Message(text="[error] No agent selected.")

        raw = getattr(self.model_config, "data", None) if self.model_config is not None else None
        if not raw:
            return Message(text="[error] No model wired in — connect 'LandIQ Config Picker' to the Model input first.")

        try:
            state = json.loads(self.property_json or "{}")
        except Exception:
            state = {}

        mode = raw.get("mode")
        label = "?"

        if mode == "saved":
            full_name = (raw.get("config_full_name") or "").strip()
            if not full_name:
                return Message(text="[error] No saved config selected on LandIQ Config Picker.")
            try:
                bind = httpx.post(
                    f"{BACKEND_URL}/agent-config/{agent_name}/set-llm-config",
                    json={"full_name": full_name},
                    timeout=15,
                )
                if bind.status_code != 200:
                    msg = f"[bind failed] HTTP {bind.status_code}: {bind.text[:200]}"
                    self.status = msg
                    return Message(text=msg)
            except Exception as e:
                msg = f"[bind error] {type(e).__name__}: {str(e)[:200]}"
                self.status = msg
                return Message(text=msg)
            label = f"saved config '{full_name}'"

        elif mode == "custom":
            provider = raw.get("provider")
            model = raw.get("model")
            key = raw.get("api_key")
            if not (provider and model and key):
                return Message(text="[error] Custom model on LandIQ Config Picker is incomplete (provider/model/key).")
            state["llm_model_override"] = f"{provider}/{model}"
            state["llm_api_key_override"] = key
            label = f"custom model '{provider}/{model}'"

        else:
            return Message(text=f"[error] Unrecognised model config mode: {mode!r}")

        try:
            r = httpx.post(
                f"{BACKEND_URL}/internal/run-single-agent",
                json={"agent_name": agent_name, **state},
                timeout=120,
            )
            data = r.json()
        except Exception as e:
            msg = f"[agent run error] {type(e).__name__}: {str(e)[:200]}"
            self.status = msg
            return Message(text=msg)

        self.status = data
        out = data.get(f"{agent_name}_output") or data
        return Message(
            text=f"[{agent_name}] ran with {label}:\n\n{json.dumps(out, indent=2, default=str)}"
        )
