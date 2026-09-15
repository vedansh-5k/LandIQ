"""
landiq_agent_config_component.py — "LandIQ Agent Config" Langflow box (Config 2, v3 — final)
-----------------------------------------------------------------------------
Config 2 — binds one agent to the ONE wired "LandIQ Model" box, not a name
string looked up in the backend's own database. Wire "LandIQ Model"'s
"Model Config" output straight into the "Model" input here — that single
box already carries the full priority-1/priority-2 chain internally, so
one wire is all this needs. The provider/model/api_key on that upstream
box (both priorities) are exactly what gets used — this box does not
know or care whether that key belongs to LandIQ or to a completely
different client.

What actually happens when you run it:
  Sends agent_name + the property data + the wired model(s)'
  provider/model/api_key explicitly to the LandIQ backend's real agent
  logic (agents_registry/<agent>/AGENT.md — prompt, RAG, JSON parsing —
  that part legitimately stays server-side, it's the actual product).
  The backend uses the model/key you wired in, not anything it has saved
  itself. If priority 2 was set on the LandIQ Model box, the backend
  builds it as a real fallback should priority 1 be unavailable.
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


class LandIQAgentConfig(Component):
    display_name = "LandIQ Agent Config"
    description = (
        "Config 2 — binds one agent (read live from agents_registry/, "
        "nothing hardcoded) to the ONE wired 'LandIQ Model' box, which "
        "already carries priority 1 and priority 2 internally. The "
        "provider/model/API key on that upstream box are what actually "
        "run this agent — no config name, no database lookup."
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
        DataInput(
            name="model_config",
            display_name="Model",
            info="Wire in 'LandIQ Model'’s Model Config output — carries both priority 1 and priority 2.",
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

    def _model_overrides(self) -> dict:
        """Reads the single wired Data object — {"primary": {...},
        "fallback": {...} or None} — and turns it into the explicit
        override fields dynamic_agent.py understands."""
        raw = getattr(self.model_config, "data", None) if self.model_config is not None else None
        raw = raw or {}
        primary = raw.get("primary") or {}
        fallback = raw.get("fallback") or {}

        overrides = {}
        if primary.get("provider") and primary.get("model"):
            overrides["llm_model_override"] = f"{primary['provider']}/{primary['model']}"
            if primary.get("api_key"):
                overrides["llm_api_key_override"] = primary["api_key"]
        if fallback.get("provider") and fallback.get("model"):
            overrides["llm_fallback_override"] = f"{fallback['provider']}/{fallback['model']}"
            if fallback.get("api_key"):
                overrides["llm_fallback_api_key_override"] = fallback["api_key"]
        return overrides

    def run_bound_agent(self) -> Message:
        import httpx

        agent_name = (self.agent_name or "").strip()
        if not agent_name:
            return Message(text="[error] No agent selected.")

        try:
            state = json.loads(self.property_json or "{}")
        except Exception:
            state = {}

        overrides = self._model_overrides()
        if not overrides:
            return Message(text="[error] No model wired in — connect 'LandIQ Model'’s Model Config output to the Model input first.")
        state.update(overrides)

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
        model_label = overrides.get("llm_model_override", "?")
        fallback_label = overrides.get("llm_fallback_override")
        out = data.get(f"{agent_name}_output") or data
        return Message(
            text=f"[{agent_name}] ran with wired model '{model_label}'"
                 f"{' (fallback: ' + fallback_label + ')' if fallback_label else ''}:\n\n"
                 f"{json.dumps(out, indent=2, default=str)}"
        )
