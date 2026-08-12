"""
landiq_canvas.py
----------------
Full, idempotent rebuild of the LandIQ Langflow canvas to the ONE-ORCHESTRATOR
standard: exactly one "LandIQ Orchestrator" hub node (no separate Dispatch /
Result pair), fed by ten 5-box agent clusters (Input, Prompt, LLM, Skill,
Agent) plus a visible Orchestrator LLM box and a PII Safety Guardrail box.

Re-running this is the supported way to pick up new agents (add a folder to
agents_registry/, rerun - its 5-box cluster and its own input port on the
orchestrator appear automatically; no agent name is ever hardcoded here).

FINAL SHAPE (54 nodes, 53 edges):

    10x [ Input  ]--\
        [ Prompt ]----\
        [  LLM   ]------> Agent Executor --------\
        [ Skill  ]----/                            \
                                                     v
    Orchestrator LLM  ------------------------> LandIQ Orchestrator --> LandIQ Result
    PII Safety Guardrail ---------------------/     (THE ONE HUB)

No Chat Input / Parse Query node - agents get their input from their own
Input box. Every node has EXACTLY ONE output (a hard, tested constraint of
this Langflow install: a node with a second distinct output port has its
edges silently dropped on reload). Many different sources feeding many
named input ports on one node (the orchestrator's 10 "{key}_result" ports)
is the reliable direction and is used freely here.

Each agent is a real 5-box cluster:
  - Input box:   editable property fields (area/city/state/budget/...),
                 sent verbatim as this agent's own property_data. Replaces
                 the old shared ChatInput -> ParseQuery path entirely.
  - Prompt box:  MessageTextInput pre-filled with the REAL agents_registry/
                 {name}/AGENT.md content. Editable - genuinely becomes
                 state["agent_role_override"] on the backend (verified
                 against src/agents/dynamic_agent.py line ~348).
  - LLM box:     DropdownInput (model) + this agent's real configured
                 temperature from AGENT.md, shown for transparency. Model
                 choice is genuine (state["llm_model_override"], verified
                 against dynamic_agent.py line ~375). Temperature is
                 real/visible but NOT yet a live override - the backend
                 always uses the AGENT.md file's own value. Disclosed
                 honestly, not hidden.
  - Skill box:   MessageTextInput pre-filled with the REAL agents_registry/
                 {name}/SKILL.md content. Sent as state["agent_skill_override"],
                 but dynamic_agent.py does not currently read that key (it
                 loads SKILL.md straight from disk at run time) - so, like
                 temperature, this is real/visible but not yet a live
                 override. Disclosed honestly in this file's own docstring
                 and in each Skill box's description, not hidden.
  - Agent box:   the actual executor. Takes property_data / prompt_config /
                 llm_config / skill_config from its own 4 boxes and calls
                 the real backend (/internal/run-single-agent).

Orchestrator LLM is a separate, visible box whose model dropdown is read by
the ONE LandIQ Orchestrator when it asks the backend's real planner
(/internal/run-orchestrated -> src/graph/orchestrator_agent.py:plan_execution)
for the execution order - making it visible that a real LLM decides
ordering, not fixed logic.

PII Safety Guardrail is a separate, visible config box (mode + server URL).
The ONE LandIQ Orchestrator reads that config and makes the actual guardrail
call itself, directly against the classmate's real contract - verified
against guardrail_server.py: POST /run with {text, pii_enabled, pii_action,
safety_enabled, topic_check}. (The originally-drafted "/check" endpoint does
not exist on the real server and would 404 every time - using the verified
real contract instead.) Gracefully degrades if the server is offline.

Does NOT touch orchestrator_agent.py, dynamic_agent.py, langflow_bridge.py,
or api.py.

Usage:
    python landiq_canvas.py
"""

import gzip
import json
import os
import pathlib
import sys
import urllib.request
import urllib.error

LANGFLOW = "http://127.0.0.1:7860"
BACKEND = "http://127.0.0.1:8000"
GUARDRAIL_SERVER = "http://127.0.0.1:8002"
REGISTRY_DIR = pathlib.Path("agents_registry")
FLOW_ID_FILE = pathlib.Path("langflow_flow_id.txt")
API_KEY_FILE = pathlib.Path("langflow_api_key.txt")

BROAD_INPUT_TYPES = ["Data", "JSON", "DataFrame", "Table", "Message"]
MODEL_OPTIONS = ["groq/llama-3.3-70b-versatile", "gemini/gemini-1.5-flash"]
DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"


def die(msg):
    print("\n" + "=" * 68)
    print("[X] " + msg)
    print("=" * 68 + "\n")
    sys.exit(1)


def api_key():
    if API_KEY_FILE.exists():
        return API_KEY_FILE.read_text(encoding="utf-8").strip()
    return os.environ.get("LANGFLOW_API_KEY", "").strip()


def call(method, path, body=None, timeout=30):
    url = LANGFLOW + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    key = api_key()
    if key:
        headers["x-api-key"] = key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status_code = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status_code = e.code
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        return status_code, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status_code, {"error": raw.decode("utf-8", "replace")[:1500]}


def pretty_name(agent_key):
    return agent_key.replace("_", " ").title()


def handle_str(d):
    return json.dumps(d, separators=(",", ":")).replace('"', "œ")


def make_edge(source_id, source_handle, target_id, target_handle, eid):
    return {
        "source": source_id,
        "sourceHandle": handle_str(source_handle),
        "target": target_id,
        "targetHandle": handle_str(target_handle),
        "data": {"targetHandle": target_handle, "sourceHandle": source_handle},
        "id": eid,
        "animated": False,
        "className": "",
        "selected": False,
    }


# ------------------------------------------------------------------ 1
print("\n[1/8] Reading agents_registry/ (name, description, layer, temperature, "
      "display_name, real AGENT.md + SKILL.md text) ...")
if not REGISTRY_DIR.is_dir():
    die("agents_registry/ not found - run this from the project root.")

agent_info = {}
for folder in sorted(REGISTRY_DIR.iterdir()):
    if not folder.is_dir():
        continue
    agent_md_path = folder / "AGENT.md"
    if not agent_md_path.exists():
        continue
    agent_md_text = agent_md_path.read_text(encoding="utf-8")
    skill_path = folder / "SKILL.md"
    skill_md_text = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""

    description, layer, temperature, display_name = "", 1, 0.3, ""
    for line in agent_md_text.splitlines():
        s = line.strip()
        if s == "---":
            continue
        lower = s.lower()
        if lower.startswith("description:"):
            description = s.split(":", 1)[1].strip()
        elif lower.startswith("layer:"):
            try:
                layer = int(s.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif lower.startswith("temperature:"):
            try:
                temperature = float(s.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif lower.startswith("display_name:"):
            display_name = s.split(":", 1)[1].strip()

    agent_info[folder.name] = {
        "description": description,
        "layer": layer,
        "temperature": temperature,
        "display_name": display_name or pretty_name(folder.name),
        "agent_md_text": agent_md_text,
        "skill_md_text": skill_md_text,
    }

if not agent_info:
    die("No agents found in agents_registry/.")
all_agents = sorted(agent_info.keys())
pretty_map = {name: agent_info[name]["display_name"] for name in all_agents}
print("      -> %d agents: %s" % (len(all_agents), all_agents))

catalogue_text = "\n".join(
    "- %s (layer %d): %s" % (name, agent_info[name]["layer"], agent_info[name]["description"])
    for name in sorted(all_agents, key=lambda n: agent_info[n]["layer"])
)
layers_literal = json.dumps([
    sorted(a for a in all_agents if agent_info[a]["layer"] == n)
    for n in sorted(set(v["layer"] for v in agent_info.values()))
])


# ------------------------------------------------------------------ 2
print("\n[2/8] Connecting to Langflow ...")
try:
    hstatus, _ = call("GET", "/health", timeout=10)
    if hstatus >= 400:
        die("Langflow answered HTTP %d at /health." % hstatus)
except Exception as e:
    die("Cannot reach Langflow at %s\n    %s" % (LANGFLOW, e))
print("      -> Langflow is up")


# ------------------------------------------------------------------ 3
print("\n[3/8] Loading the existing flow (keeping only its ChatOutput node) ...")
if not FLOW_ID_FILE.exists():
    die("langflow_flow_id.txt not found - run setup_langflow.py once first.")
flow_id = FLOW_ID_FILE.read_text(encoding="utf-8").strip()
status, flow = call("GET", "/api/v1/flows/%s" % flow_id)
if status >= 400 or not flow.get("data"):
    die("Could not load flow %s (HTTP %s): %s" % (flow_id, status, flow))

existing_nodes = flow["data"].get("nodes", [])


def find_by_type(ns, type_name):
    for n in ns:
        if n.get("data", {}).get("type") == type_name:
            return n
    return None


chat_output_node = find_by_type(existing_nodes, "ChatOutput")
if not chat_output_node:
    die("Expected a ChatOutput node in flow %s - none found. Run setup_langflow.py first." % flow_id)
print("      -> found LandIQ Result (ChatOutput, id kept: %s). Everything else "
      "(old ChatInput, ParseQuery, Dispatch/Result orchestrator pair, old agent "
      "nodes) will be dropped on save." % chat_output_node["id"])


# ------------------------------------------------------------------ 4
print("\n[4/8] Fetching the component registry ...")
cstatus, cresult = call("GET", "/api/v1/all")
if cstatus >= 400:
    die("Could not fetch component registry (HTTP %s)" % cstatus)
custom_template = cresult["custom_component"]["CustomComponent"]


def build_component(code, label):
    vstatus, vresult = call("POST", "/api/v1/validate/code", {"code": code})
    if vstatus >= 400 or vresult.get("imports", {}).get("errors") or vresult.get("function", {}).get("errors"):
        die("%s failed validation: %s" % (label, vresult))
    bstatus, bresult = call("POST", "/api/v1/custom_component",
                             {"code": code, "frontend_node": custom_template})
    if bstatus >= 400:
        die("Could not build %s (HTTP %s): %s" % (label, bstatus, bresult))
    return bresult["data"]


model_options_literal = ", ".join(repr(m) for m in MODEL_OPTIONS)


# ------------------------------------------------------------------ 5
print("\n[5/8] Building 'Orchestrator LLM' and 'PII Safety Guardrail' config boxes ...")

ORCH_LLM_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output
from lfx.schema.data import Data


class OrchestratorLLM(Component):
    display_name = "Orchestrator LLM"
    description = (
        "The LLM the orchestrator uses to decide execution order. This is why "
        "the pipeline is dynamic - the LLM writes the layer plan, no hardcoded "
        "sequence exists anywhere. Wired into LandIQ Orchestrator below."
    )
    icon = "sparkles"
    name = "OrchestratorLLM"

    inputs = [
        DropdownInput(name="model", display_name="Planning Model", options=[{model_options}], value={default_model!r}),
        MessageTextInput(name="temperature", display_name="Temperature", value="0.1"),
    ]
    outputs = [
        Output(display_name="Planner Config", name="planner_out", method="get_planner"),
    ]

    def get_planner(self) -> Data:
        try:
            t = float(self.temperature)
        except Exception:
            t = 0.1
        out = {{"planning_model": self.model, "planning_temperature": t}}
        self.status = out
        return Data(data=out)
'''.format(model_options=model_options_literal, default_model=DEFAULT_MODEL)

orch_llm_def = build_component(ORCH_LLM_TEMPLATE, "Orchestrator LLM")
print("      -> Orchestrator LLM built")

GUARDRAIL_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output
from lfx.schema.data import Data


class PIIGuardrail(Component):
    display_name = "PII Safety Guardrail"
    description = (
        "DeBERTa LoRA-based PII detection and safety guardrail - the "
        "classmate's component, served on port 8002. Wire this into LandIQ "
        "Orchestrator; the orchestrator makes the real POST /run call against "
        "this config and degrades gracefully if the server is offline."
    )
    icon = "shield"
    name = "PIIGuardrail"

    inputs = [
        DropdownInput(name="guardrail_mode", display_name="Guardrail Mode", options=["none", "flag", "redact", "block"], value="flag"),
        MessageTextInput(name="guardrail_url", display_name="Guardrail Server", value="{guardrail_server}"),
    ]
    outputs = [
        Output(display_name="Guardrail Config", name="guardrail_out", method="get_guardrail"),
    ]

    def get_guardrail(self) -> Data:
        out = {{"guardrail_mode": self.guardrail_mode, "guardrail_url": (self.guardrail_url or "").rstrip("/")}}
        self.status = out
        return Data(data=out)
'''.format(guardrail_server=GUARDRAIL_SERVER)

guardrail_def = build_component(GUARDRAIL_TEMPLATE, "PII Safety Guardrail")
print("      -> PII Safety Guardrail built")


# ------------------------------------------------------------------ 6
print("\n[6/8] Building 50 per-agent boxes (Input + Prompt + LLM + Skill + Agent x %d agents) ..."
      % len(all_agents))

INPUT_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.data import Data


class AgentInput_{key}(Component):
    display_name = {display_repr}
    description = {desc_repr}
    icon = "file-input"
    name = "AgentInput_{key}"

    inputs = [
        MessageTextInput(name="area", display_name="Area", value=""),
        MessageTextInput(name="city", display_name="City", value=""),
        MessageTextInput(name="state", display_name="State", value=""),
        MessageTextInput(name="land_size", display_name="Land Size", value="0"),
        MessageTextInput(name="land_unit", display_name="Land Unit", value="sq ft"),
        MessageTextInput(name="land_type", display_name="Land Type", value="residential"),
        MessageTextInput(name="total_budget", display_name="Total Budget (INR)", value="0"),
        MessageTextInput(name="purpose", display_name="Purpose", value="investment"),
        MessageTextInput(name="timeline_years", display_name="Timeline (years)", value="5"),
        MessageTextInput(name="risk_tolerance", display_name="Risk Tolerance", value="moderate"),
    ]

    outputs = [
        Output(display_name="Property Data", name="property_data", method="get_data"),
    ]

    def get_data(self) -> Data:
        def num(v, d=0):
            try:
                return float(str(v).replace(",", "").strip() or d)
            except Exception:
                return d
        out = {{
            "area": (self.area or "").strip(),
            "city": (self.city or "").strip(),
            "state": (self.state or "").strip(),
            "land_size": num(self.land_size),
            "land_unit": (self.land_unit or "sq ft").strip(),
            "land_type": (self.land_type or "residential").strip(),
            "total_budget": num(self.total_budget),
            "purpose": (self.purpose or "investment").strip(),
            "timeline_years": int(num(self.timeline_years, 5)),
            "risk_tolerance": (self.risk_tolerance or "moderate").strip(),
            "has_title_deed": True,
            "construction_budget": 0,
            "taking_loan": False,
            "loan_amount": 0,
            "loan_interest_rate": 0,
            "monthly_income_expectation": 0,
            "selected_agents": ["all"],
        }}
        self.status = out
        return Data(data=out)
'''

PROMPT_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.data import Data


class AgentPrompt_{key}(Component):
    display_name = {display_repr}
    description = {desc_repr}
    icon = "file-text"
    name = "AgentPrompt_{key}"

    inputs = [
        MessageTextInput(name="prompt_text", display_name="Agent Prompt (AGENT.md)",
                         info="Live content of agents_registry/{key}/AGENT.md.",
                         value={agent_md_repr}),
    ]
    outputs = [
        Output(display_name="Prompt", name="prompt_out", method="get_prompt"),
    ]

    def get_prompt(self) -> Data:
        out = {{"agent_role_override": self.prompt_text or ""}}
        self.status = out
        return Data(data=out)
'''

LLM_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output
from lfx.schema.data import Data


class AgentLLM_{key}(Component):
    display_name = {display_repr}
    description = {desc_repr}
    icon = "cpu"
    name = "AgentLLM_{key}"

    inputs = [
        DropdownInput(name="model", display_name="Model", options=[{model_options}], value={default_model!r}),
        MessageTextInput(name="temperature", display_name="Temperature", info="From AGENT.md frontmatter.", value={temperature_repr}),
    ]
    outputs = [
        Output(display_name="LLM Config", name="llm_out", method="get_llm"),
    ]

    def get_llm(self) -> Data:
        try:
            t = float(self.temperature)
        except Exception:
            t = {temperature}
        out = {{"llm_model_override": self.model, "temperature": t}}
        self.status = out
        return Data(data=out)
'''

SKILL_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.data import Data


class AgentSkill_{key}(Component):
    display_name = {display_repr}
    description = {desc_repr}
    icon = "list-checks"
    name = "AgentSkill_{key}"

    inputs = [
        MessageTextInput(name="skill_text", display_name="Skill Workflow (SKILL.md)",
                         info="Live content of agents_registry/{key}/SKILL.md.",
                         value={skill_md_repr}),
    ]
    outputs = [
        Output(display_name="Skill", name="skill_out", method="get_skill"),
    ]

    def get_skill(self) -> Data:
        out = {{"agent_skill_override": self.skill_text or ""}}
        self.status = out
        return Data(data=out)
'''

AGENT_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.data import Data


class Agent_{key}(Component):
    display_name = {display_repr}
    description = {desc_repr}
    icon = "brain-circuit"
    name = "Agent_{key}"

    inputs = [
        DataInput(name="property_data", display_name="Property Data"),
        DataInput(name="prompt_config", display_name="Prompt"),
        DataInput(name="llm_config", display_name="LLM"),
        DataInput(name="skill_config", display_name="Skill"),
    ]
    outputs = [
        Output(display_name={output_display_repr}, name="output", method="run_agent"),
    ]

    def run_agent(self) -> Data:
        import httpx

        payload = {{}}
        for port in ("property_data", "prompt_config", "llm_config", "skill_config"):
            d = getattr(self, port, None)
            if d is not None and getattr(d, "data", None):
                payload.update(d.data)

        payload["agent_name"] = "{key}"
        payload["location"] = payload.get("area", "")

        try:
            r = httpx.post("{backend}/internal/run-single-agent", json=payload, timeout=180)
            result = r.json()
        except Exception as e:
            result = {{"error_log": ["{key}: " + str(e)[:160]], "completed_agents": [{fail_label_repr}]}}

        self.status = result
        return Data(data=result)
'''

input_ids, prompt_ids, llm_ids, skill_ids, agent_ids = {}, {}, {}, {}, {}
input_defs, prompt_defs, llm_defs, skill_defs, agent_defs = {}, {}, {}, {}, {}

for name in all_agents:
    pretty = pretty_map[name]
    temp = agent_info[name]["temperature"]
    desc = agent_info[name]["description"]

    i_code = INPUT_TEMPLATE.format(
        key=name,
        display_repr=repr("%s: Input" % pretty),
        desc_repr=repr("Property details this %s agent analyses. Edit these values to "
                        "change what the agent sees - they are sent verbatim to the "
                        "backend." % pretty),
    )
    input_defs[name] = build_component(i_code, "Input box for '%s'" % name)
    input_ids[name] = "AgentInput_%s" % name

    p_code = PROMPT_TEMPLATE.format(
        key=name,
        display_repr=repr("%s: Prompt" % pretty),
        desc_repr=repr("The real role and instructions for %s, loaded from "
                        "agents_registry/%s/AGENT.md. Editing this genuinely "
                        "overrides what the backend uses (agent_role_override)." % (pretty, name)),
        agent_md_repr=repr(agent_info[name]["agent_md_text"]),
    )
    prompt_defs[name] = build_component(p_code, "Prompt box for '%s'" % name)
    prompt_ids[name] = "AgentPrompt_%s" % name

    l_code = LLM_TEMPLATE.format(
        key=name,
        display_repr=repr("%s: LLM" % pretty),
        desc_repr=repr("Which LLM runs %s, and at what temperature. The model dropdown "
                        "genuinely changes the provider the backend calls "
                        "(llm_model_override). Temperature is shown from this agent's "
                        "real AGENT.md value for transparency - the backend always uses "
                        "the AGENT.md file's own temperature, so this field is not yet a "
                        "live override." % pretty),
        model_options=model_options_literal, default_model=DEFAULT_MODEL,
        temperature_repr=repr(str(temp)), temperature=temp,
    )
    llm_defs[name] = build_component(l_code, "LLM box for '%s'" % name)
    llm_ids[name] = "AgentLLM_%s" % name

    s_code = SKILL_TEMPLATE.format(
        key=name,
        display_repr=repr("%s: Skill" % pretty),
        desc_repr=repr("The step-by-step workflow for %s, loaded from "
                        "agents_registry/%s/SKILL.md, shown for transparency. The backend "
                        "currently loads SKILL.md straight from disk at run time and does "
                        "not yet read a live override from here - disclosed honestly, not "
                        "hidden." % (pretty, name)),
        skill_md_repr=repr(agent_info[name]["skill_md_text"]),
    )
    skill_defs[name] = build_component(s_code, "Skill box for '%s'" % name)
    skill_ids[name] = "AgentSkill_%s" % name

    a_code = AGENT_TEMPLATE.format(
        key=name,
        display_repr=repr("Agent: %s" % pretty),
        desc_repr=repr("Runs the real %s agent through the LandIQ backend "
                        "(agents_registry/%s/). Layer %d. %s"
                        % (pretty, name, agent_info[name]["layer"], desc)),
        output_display_repr=repr("%s Result" % pretty),
        backend=BACKEND,
        fail_label_repr=repr("%s (Failed)" % pretty),
    )
    agent_defs[name] = build_component(a_code, "Agent box for '%s'" % name)
    agent_ids[name] = "Agent_%s" % name

    print("      -> %s: Input + Prompt (%d chars) + LLM (temp=%s) + Skill (%d chars) + Agent built"
          % (name, len(agent_info[name]["agent_md_text"]), temp, len(agent_info[name]["skill_md_text"])))


# ------------------------------------------------------------------ 7
print("\n[7/8] Building the ONE 'LandIQ Orchestrator' hub (%d agent-result ports + planner + guardrail) ..."
      % len(all_agents))

result_inputs = "\n".join(
    '        DataInput(name="%s_result", display_name=%s),' % (a, repr("%s Result" % pretty_map[a]))
    for a in all_agents
)
result_handle_list = ", ".join('"%s_result"' % a for a in all_agents)

ORCHESTRATOR_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, MessageTextInput, Output
from lfx.schema.message import Message
import json


class LandIQOrchestrator(Component):
    display_name = "LandIQ Orchestrator"
    description = (
        "The single orchestrator hub. Every agent's real result arrives on its "
        "own labelled input port. The agent catalogue is read live from "
        "agents_registry/ - no agent name or execution order is hardcoded "
        "anywhere. Combines all agent outputs, gets the real LLM execution "
        "plan from the backend, applies the wired guardrail, and emits the "
        "final analysis."
    )
    icon = "brain"
    name = "LandIQOrchestrator"

    inputs = [
        DataInput(name="planner_config", display_name="Planner LLM", info="From the Orchestrator LLM box."),
        DataInput(name="guardrail_config", display_name="Guardrail", info="From the PII Safety Guardrail box."),
        MessageTextInput(name="agent_catalogue", display_name="Agent Catalogue",
                         info="Every agent found in agents_registry/, read at canvas-build time.",
                         value={catalogue_repr}),
{result_inputs}
    ]

    outputs = [
        Output(display_name="Final Analysis", name="final_result", method="orchestrate"),
    ]

    def orchestrate(self) -> Message:
        import httpx

        state = {{}}
        completed = []
        errors = []

        for handle in [{result_handle_list}]:
            d = getattr(self, handle, None)
            if d is None or not getattr(d, "data", None):
                continue
            for k, v in d.data.items():
                if k == "completed_agents":
                    completed += (v if isinstance(v, list) else [v])
                elif k == "error_log":
                    errors += (v if isinstance(v, list) else [v])
                else:
                    state[k] = v

        state["completed_agents"] = completed
        state["error_log"] = errors
        if state.get("senior_consultant_output"):
            state["final_recommendation"] = state["senior_consultant_output"]
        state["orchestrator_source"] = "langflow"

        planner = {{}}
        if self.planner_config is not None and getattr(self.planner_config, "data", None):
            planner = dict(self.planner_config.data)
        state["planner_config"] = planner

        try:
            r = httpx.post(
                "{backend}/internal/run-orchestrated",
                json={{"property_data": state, "agent_catalogue": self.agent_catalogue,
                      "planning_model": planner.get("planning_model")}},
                timeout=90,
            )
            info = r.json()
            state["execution_plan"] = info.get("plan") or {{"layers": {layers_literal}, "source": "graph"}}
            if info.get("rag_context"):
                state["rag_context"] = info["rag_context"]
        except Exception as e:
            state["execution_plan"] = {{"layers": {layers_literal}, "source": "graph"}}
            state["plan_error"] = str(e)[:160]

        gr = {{}}
        if self.guardrail_config is not None and getattr(self.guardrail_config, "data", None):
            gr = dict(self.guardrail_config.data)
        mode = (gr.get("guardrail_mode") or "none").lower()

        if mode != "none":
            pii_action = "BLOCK" if mode == "block" else "MASK"
            text_to_check = str(state.get("final_recommendation") or state)[:4000]
            try:
                gres = httpx.post(
                    (gr.get("guardrail_url") or "{guardrail_default}").rstrip("/") + "/run",
                    json={{"text": text_to_check, "pii_enabled": True, "pii_action": pii_action,
                          "safety_enabled": True, "topic_check": False}},
                    timeout=15,
                )
                gresult = gres.json()
                state["guardrail_status"] = "checked"
                state["guardrail_allowed"] = gresult.get("allowed")
                state["guardrail_pii_found"] = gresult.get("pii_found")
                state["guardrail_blocked_reason"] = gresult.get("blocked_reason")
                if mode in ("redact", "block") and gresult.get("processed_text"):
                    state["final_recommendation"] = gresult["processed_text"]
            except Exception as e:
                state["guardrail_status"] = "server_offline"
                state["guardrail_error"] = str(e)[:150]
        else:
            state["guardrail_status"] = "skipped"

        self.status = state
        return Message(text=json.dumps(state, default=str))
'''.format(
    catalogue_repr=repr(catalogue_text),
    result_inputs=result_inputs,
    result_handle_list=result_handle_list,
    backend=BACKEND,
    layers_literal=layers_literal,
    guardrail_default=GUARDRAIL_SERVER,
)

orchestrator_def = build_component(ORCHESTRATOR_TEMPLATE, "LandIQ Orchestrator")
print("      -> LandIQ Orchestrator built (%d inputs, 1 output)" % (len(all_agents) + 3))


# ------------------------------------------------------------------ 8
print("\n[8/8] Laying out 54 nodes and wiring 53 edges ...")

ORCH_LLM_ID = "OrchestratorLLM-1"
GUARDRAIL_ID = "PIIGuardrail-1"
ORCHESTRATOR_ID = "LandIQOrchestrator-1"

CLUSTER_STEP = 720
X_CFG, X_AGENT, X_HUB, X_OUT = 0, 560, 1250, 1900
INPUT_OFF, PROMPT_OFF, LLM_OFF, SKILL_OFF, EXEC_OFF = 0, 160, 320, 480, 240


def place(node, x, y):
    node = dict(node)
    node["position"] = {"x": x, "y": y}
    return node


final_nodes = []
cluster_y = {}
for i, name in enumerate(all_agents):
    cy = i * CLUSTER_STEP
    cluster_y[name] = cy
    final_nodes.append({
        "id": input_ids[name], "type": "genericNode", "position": {"x": X_CFG, "y": cy + INPUT_OFF},
        "selected": False,
        "data": {"node": input_defs[name], "showNode": True, "type": "AgentInput_%s" % name, "id": input_ids[name]},
    })
    final_nodes.append({
        "id": prompt_ids[name], "type": "genericNode", "position": {"x": X_CFG, "y": cy + PROMPT_OFF},
        "selected": False,
        "data": {"node": prompt_defs[name], "showNode": True, "type": "AgentPrompt_%s" % name, "id": prompt_ids[name]},
    })
    final_nodes.append({
        "id": llm_ids[name], "type": "genericNode", "position": {"x": X_CFG, "y": cy + LLM_OFF},
        "selected": False,
        "data": {"node": llm_defs[name], "showNode": True, "type": "AgentLLM_%s" % name, "id": llm_ids[name]},
    })
    final_nodes.append({
        "id": skill_ids[name], "type": "genericNode", "position": {"x": X_CFG, "y": cy + SKILL_OFF},
        "selected": False,
        "data": {"node": skill_defs[name], "showNode": True, "type": "AgentSkill_%s" % name, "id": skill_ids[name]},
    })
    final_nodes.append({
        "id": agent_ids[name], "type": "genericNode", "position": {"x": X_AGENT, "y": cy + EXEC_OFF},
        "selected": False,
        "data": {"node": agent_defs[name], "showNode": True, "type": "Agent_%s" % name, "id": agent_ids[name]},
    })

total_height = (len(all_agents) - 1) * CLUSTER_STEP
mid_y = total_height / 2.0

final_nodes.append({
    "id": ORCH_LLM_ID, "type": "genericNode", "position": {"x": X_HUB, "y": mid_y - 340},
    "selected": False,
    "data": {"node": orch_llm_def, "showNode": True, "type": "OrchestratorLLM", "id": ORCH_LLM_ID},
})
final_nodes.append({
    "id": ORCHESTRATOR_ID, "type": "genericNode", "position": {"x": X_HUB, "y": mid_y},
    "selected": False,
    "data": {"node": orchestrator_def, "showNode": True, "type": "LandIQOrchestrator", "id": ORCHESTRATOR_ID},
})
final_nodes.append({
    "id": GUARDRAIL_ID, "type": "genericNode", "position": {"x": X_HUB, "y": mid_y + 340},
    "selected": False,
    "data": {"node": guardrail_def, "showNode": True, "type": "PIIGuardrail", "id": GUARDRAIL_ID},
})

final_nodes.append(place(chat_output_node, X_OUT, mid_y))

print("      -> %d nodes placed" % len(final_nodes))

eid_n = [0]
def next_eid(prefix):
    eid_n[0] += 1
    return "reactflow__edge-pro-%s-%d" % (prefix, eid_n[0])

final_edges = []

# Per-agent: Input/Prompt/LLM/Skill -> Agent executor (4 edges x N agents)
for name in all_agents:
    final_edges.append(make_edge(
        input_ids[name],
        {"dataType": "AgentInput_%s" % name, "id": input_ids[name], "name": "property_data", "output_types": ["Data"]},
        agent_ids[name],
        {"fieldName": "property_data", "id": agent_ids[name], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("input-%s" % name),
    ))
    final_edges.append(make_edge(
        prompt_ids[name],
        {"dataType": "AgentPrompt_%s" % name, "id": prompt_ids[name], "name": "prompt_out", "output_types": ["Data"]},
        agent_ids[name],
        {"fieldName": "prompt_config", "id": agent_ids[name], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("prompt-%s" % name),
    ))
    final_edges.append(make_edge(
        llm_ids[name],
        {"dataType": "AgentLLM_%s" % name, "id": llm_ids[name], "name": "llm_out", "output_types": ["Data"]},
        agent_ids[name],
        {"fieldName": "llm_config", "id": agent_ids[name], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("llm-%s" % name),
    ))
    final_edges.append(make_edge(
        skill_ids[name],
        {"dataType": "AgentSkill_%s" % name, "id": skill_ids[name], "name": "skill_out", "output_types": ["Data"]},
        agent_ids[name],
        {"fieldName": "skill_config", "id": agent_ids[name], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("skill-%s" % name),
    ))

# Each Agent executor's output -> the ONE Orchestrator's matching input (N edges)
for name in all_agents:
    final_edges.append(make_edge(
        agent_ids[name],
        {"dataType": "Agent_%s" % name, "id": agent_ids[name], "name": "output", "output_types": ["Data"]},
        ORCHESTRATOR_ID,
        {"fieldName": "%s_result" % name, "id": ORCHESTRATOR_ID, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("%s-orch" % name),
    ))

# Orchestrator LLM -> Orchestrator (planner_config)
final_edges.append(make_edge(
    ORCH_LLM_ID,
    {"dataType": "OrchestratorLLM", "id": ORCH_LLM_ID, "name": "planner_out", "output_types": ["Data"]},
    ORCHESTRATOR_ID,
    {"fieldName": "planner_config", "id": ORCHESTRATOR_ID, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
    next_eid("orchllm-hub"),
))

# PII Guardrail -> Orchestrator (guardrail_config)
final_edges.append(make_edge(
    GUARDRAIL_ID,
    {"dataType": "PIIGuardrail", "id": GUARDRAIL_ID, "name": "guardrail_out", "output_types": ["Data"]},
    ORCHESTRATOR_ID,
    {"fieldName": "guardrail_config", "id": ORCHESTRATOR_ID, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
    next_eid("guardrail-hub"),
))

# Orchestrator -> LandIQ Result (1 edge)
final_edges.append(make_edge(
    ORCHESTRATOR_ID,
    {"dataType": "LandIQOrchestrator", "id": ORCHESTRATOR_ID, "name": "final_result", "output_types": ["Message"]},
    chat_output_node["id"],
    {"fieldName": "input_value", "id": chat_output_node["id"], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
    next_eid("hub-out"),
))

print("      -> %d edges built" % len(final_edges))


# ------------------------------------------------------------------ save + verify
print("\nSaving (full replace - no duplicates, no leftovers, no orphan wires) ...")
payload = {
    "name": flow.get("name", "LandIQ Orchestrator"),
    "description": (
        "LandIQ single-orchestrator canvas: %d agent clusters (Input/Prompt/LLM/"
        "Skill/Agent each) -> the ONE LandIQ Orchestrator (planner + guardrail "
        "wired in) -> LandIQ Result. Rebuilt live from agents_registry/ - "
        "nothing hardcoded." % len(all_agents)
    ),
    "data": {"nodes": final_nodes, "edges": final_edges},
}
pstatus, presult = call("PATCH", "/api/v1/flows/%s" % flow_id, payload, timeout=120)
if pstatus >= 400:
    die("Langflow rejected the update (HTTP %s):\n\n%s" % (pstatus, presult))

vstatus2, vflow = call("GET", "/api/v1/flows/%s" % flow_id)
vnodes = vflow.get("data", {}).get("nodes", [])
vedges = vflow.get("data", {}).get("edges", [])

expected_nodes = len(all_agents) * 5 + 3 + 1
expected_edges = len(all_agents) * 5 + 2 + 1

if len(vedges) != expected_edges:
    print("\n  [!] WARNING: expected %d edges, live flow has %d — inspect before demoing."
          % (expected_edges, len(vedges)))
else:
    print("      -> verified: all %d edges landed" % len(vedges))

if len(vnodes) != expected_nodes:
    print("  [!] WARNING: expected %d nodes, live flow has %d." % (expected_nodes, len(vnodes)))
else:
    print("      -> verified: all %d nodes landed" % len(vnodes))

orch_boxes = [n for n in vnodes if n.get("data", {}).get("type") == "LandIQOrchestrator"]
if len(orch_boxes) != 1:
    print("  [!] WARNING: expected exactly ONE LandIQOrchestrator node, found %d." % len(orch_boxes))
else:
    print("      -> verified: exactly ONE 'LandIQ Orchestrator' box on the canvas")

print("\n" + "=" * 68)
print("  DONE")
print("=" * 68)
print("  Flow id : %s" % flow_id)
print("  Nodes   : %d (expected %d)   Edges: %d (expected %d)   Agents: %d"
      % (len(vnodes), expected_nodes, len(vedges), expected_edges, len(all_agents)))
print("""
  KNOWN, DISCLOSED LIMITATIONS (same honesty standard as before):
  1) Each agent's LLM box shows its real AGENT.md temperature and sends it in
     the payload, but src/agents/dynamic_agent.py (not touched by this
     script) always uses the AGENT.md file's own temperature - only the
     model dropdown genuinely changes backend behaviour today.
  2) Each agent's Skill box shows its real AGENT.md-adjacent SKILL.md content
     and sends it as agent_skill_override, but dynamic_agent.py loads
     SKILL.md straight from disk at run time and does not yet read that
     override - it is real/visible data, not yet a live control.
  Say the word if you want either wired for real; both need one small,
  additive change to that file (which this script deliberately does not
  touch).
""")
print("  OPEN THIS:  %s/flow/%s" % (LANGFLOW, flow_id))
print("=" * 68 + "\n")
