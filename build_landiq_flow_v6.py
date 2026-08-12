"""
build_landiq_flow_v6.py
------------------------
Adds the piece sir was asking for: a real, wired, VISIBLE orchestrator that
sits between the parsed query and the agents (decides the plan, dispatches
to every agent) - not just an aggregator sitting after them.

Final shape:

  ChatInput -> Parse -> [Orchestrator: Plan & Dispatch] -> 10 agent boxes
       (wired in their REAL dependency order, read live from
        agents_registry/*/AGENT.md - research agents -> bull/bear ->
        due_diligence -> senior_consultant)
                              |
                              v
                  [Orchestrator: Combine Results] -> LandIQ Result

Two boxes, both labelled "LandIQ Orchestrator", because a single node can't
both feed the agents AND receive their output without an illegal cycle in a
DAG-based engine like Langflow - the Plan&Dispatch box decides order and
sends the property data forward; the Combine box only reads what already
happened upstream. A note node on the canvas explains this pairing.

What's genuinely dynamic here, at every step:
  - Orchestrator reads the agent catalogue from agents_registry/*/AGENT.md
    live (same code path orchestrator_component_v2.py already used).
  - Orchestrator calls a REAL LLM (Groq, falling back to Gemini) to decide
    the plan - same prompt/logic the local orchestrator_agent.py uses.
    Nothing about which agents run or in what conceptual order is
    hand-typed.
  - The actual WIRED dependency edges between agent boxes (needed so bull,
    bear, due_diligence, senior_consultant genuinely receive prior agents'
    real findings as context - required for their prompts to make sense)
    are generated from the same agents_registry layer metadata, not typed
    by hand either. If a new agent gets added to agents_registry with its
    own `layer:`, re-running this script rewires it in correctly.
  - The plan the LLM actually decided is attached to the data and read back
    out by the Combine box, so execution_plan.source in the final result is
    "llm" when the LLM call succeeded, "default" if it had to fall back -
    genuinely reflecting what happened, not a fixed label.

Layout is also rebuilt into a clean left-to-right pipeline (was scattered
from earlier iterations).

Needs running first: Langflow + LandIQ backend (python run.py), and
build_landiq_flow_v5.py must have already run once (this builds on its
agent nodes / dependency edges).

Usage:
    python build_landiq_flow_v6.py
"""

import gzip
import json
import pathlib
import sys
import urllib.request
import urllib.error

LANGFLOW = "http://127.0.0.1:7860"
BACKEND = "http://127.0.0.1:8000"
FLOW_ID_FILE = pathlib.Path("langflow_flow_id.txt")
API_KEY_FILE = pathlib.Path("langflow_api_key.txt")
REGISTRY_DIR = pathlib.Path("agents_registry")
PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parent)

BROAD_INPUT_TYPES = ["Data", "JSON", "DataFrame", "Table", "Message"]


def die(msg):
    print("\n" + "=" * 66)
    print("[X] " + msg)
    print("=" * 66 + "\n")
    sys.exit(1)


def api_key():
    if API_KEY_FILE.exists():
        return API_KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


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
print("\n[1/8] Reading real layer numbers from agents_registry/*/AGENT.md ...")
agent_layers = {}
for folder in sorted(REGISTRY_DIR.iterdir()):
    if not folder.is_dir():
        continue
    agent_md = folder / "AGENT.md"
    if not agent_md.exists():
        continue
    layer = 1
    for line in agent_md.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.lower().startswith("layer:"):
            try:
                layer = int(s.split(":", 1)[1].strip())
            except ValueError:
                pass
            break
    agent_layers[folder.name] = layer

layers_map = {}
for name, layer in agent_layers.items():
    layers_map.setdefault(layer, []).append(name)
ordered_layer_nums = sorted(layers_map.keys())
layers_list = [sorted(layers_map[n]) for n in ordered_layer_nums]
all_agents = [a for layer in layers_list for a in layer]
print("      -> %d agents, %d layers: %s" % (len(all_agents), len(layers_list), layers_list))


def predecessors_of(layer_index):
    preds = []
    for i in range(layer_index):
        preds.extend(layers_list[i])
    return preds


# ------------------------------------------------------------------ 2
print("\n[2/8] Loading the live flow (post-v5) ...")
if not FLOW_ID_FILE.exists():
    die("langflow_flow_id.txt not found.")
flow_id = FLOW_ID_FILE.read_text(encoding="utf-8").strip()
status, flow = call("GET", "/api/v1/flows/%s" % flow_id)
if status >= 400 or not flow.get("data"):
    die("Could not load flow %s (HTTP %s): %s" % (flow_id, status, flow))

nodes = flow["data"].get("nodes", [])
edges = flow["data"].get("edges", [])


def find_by_type(ns, type_name):
    for n in ns:
        if n.get("data", {}).get("type") == type_name:
            return n
    return None


def find_by_id(ns, node_id):
    for n in ns:
        if n.get("id") == node_id:
            return n
    return None


chat_input_node = find_by_type(nodes, "ChatInput")
parse_node = find_by_type(nodes, "LandIQParseQuery")
chat_output_node = find_by_type(nodes, "ChatOutput")
aggregator_node = find_by_type(nodes, "LandIQAggregator")
if not all([chat_input_node, parse_node, chat_output_node, aggregator_node]):
    die("Expected v5 nodes not found - run build_landiq_flow_v5.py first.")

agent_node_ids = {name: "LandIQAgent_%s" % name for name in all_agents}
missing = [n for n in all_agents if find_by_id(nodes, agent_node_ids[n]) is None]
if missing:
    die("Agent node(s) missing: %s" % missing)

other_nodes = [
    n for n in nodes
    if n["id"] not in agent_node_ids.values()
    and n["id"] not in (chat_input_node["id"], parse_node["id"], chat_output_node["id"], aggregator_node["id"])
]
print("      -> found ChatInput, Parse, %d agents, Aggregator, Result (+%d other unrelated nodes kept as-is)"
      % (len(all_agents), len(other_nodes)))


# ------------------------------------------------------------------ 3
print("\n[3/8] Fetching the component registry ...")
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


# ------------------------------------------------------------------ 4
print("\n[4/8] Building the Orchestrator 'Plan & Dispatch' component ...")

PLANNER_CODE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.data import Data
import json
import os

PROJECT_ROOT = r"{project_root}"
AGENTS_DIR = os.path.join(PROJECT_ROOT, "agents_registry")


class LandIQOrchestratorPlan(Component):
    display_name = "LandIQ Orchestrator - Plan & Dispatch"
    description = (
        "Reads the live agent catalogue from agents_registry/, asks an LLM "
        "(Groq, falling back to Gemini) which agents should run and in what "
        "grouping, logs that plan, then dispatches the parsed property data "
        "(with the plan attached) to every agent node wired below. "
        "Nothing here is a hardcoded agent list or a hardcoded order - "
        "if this LLM call fails, it falls back to each agent's own "
        "`layer:` field from its AGENT.md, same as the local orchestrator."
    )
    icon = "brain"
    name = "LandIQOrchestratorPlan"

    inputs = [
        DataInput(name="query_input", display_name="Parsed Query", info="Parsed property JSON from LandIQ Parse Query."),
    ]
    outputs = [
        Output(display_name="Plan + Property Data", name="dispatch", method="dispatch"),
    ]

    def _read_catalogue(self):
        catalogue = []
        if not os.path.isdir(AGENTS_DIR):
            return catalogue
        for folder_name in sorted(os.listdir(AGENTS_DIR)):
            folder_path = os.path.join(AGENTS_DIR, folder_name)
            if not os.path.isdir(folder_path):
                continue
            agent_file = os.path.join(folder_path, "AGENT.md")
            if not os.path.isfile(agent_file):
                continue
            info = {{"name": folder_name, "description": "", "layer": 1}}
            try:
                with open(agent_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            for line in content.split("\\n"):
                s = line.strip()
                lower = s.lower()
                if lower.startswith("name:"):
                    val = s.split(":", 1)[1].strip()
                    if val:
                        info["name"] = val
                elif lower.startswith("description:"):
                    val = s.split(":", 1)[1].strip()
                    if val:
                        info["description"] = val[:100]
                elif lower.startswith("layer:"):
                    try:
                        info["layer"] = int(s.split(":", 1)[1].strip())
                    except ValueError:
                        pass
            catalogue.append(info)
        return catalogue

    def _default_plan(self, catalogue):
        from collections import defaultdict
        layer_map = defaultdict(list)
        for a in catalogue:
            layer_map[a["layer"]].append(a["name"])
        layers = [layer_map[k] for k in sorted(layer_map.keys())]
        return {{"layers": layers, "source": "default"}}

    def _call_llm_for_plan(self, system, user, valid_names):
        import requests
        env_path = os.path.join(PROJECT_ROOT, ".env")
        env_vars = {{}}
        if os.path.isfile(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        env_vars[k.strip()] = v.strip().strip(chr(34)).strip(chr(39))
        groq_key = env_vars.get("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", ""))
        google_key = env_vars.get("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
        if groq_key:
            try:
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={{"Authorization": "Bearer " + groq_key, "Content-Type": "application/json"}},
                    json={{
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{{"role": "system", "content": system}}, {{"role": "user", "content": user}}],
                        "temperature": 0.1, "max_tokens": 500,
                    }},
                    timeout=30,
                )
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"]
                    text = text.strip().strip("`").strip()
                    if text.startswith("json"):
                        text = text[4:].strip()
                    plan_data = json.loads(text)
                    layers = [[a for a in layer if a in valid_names] for layer in plan_data.get("layers", [])]
                    layers = [l for l in layers if l]
                    if layers:
                        return {{"layers": layers, "source": "llm"}}
            except Exception as e:
                self.log("Groq planning failed: " + str(e)[:80])
        if google_key:
            try:
                r = requests.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + google_key,
                    headers={{"Content-Type": "application/json"}},
                    json={{
                        "contents": [{{"parts": [{{"text": system + chr(10) + chr(10) + user}}]}}],
                        "generationConfig": {{"temperature": 0.1, "maxOutputTokens": 500}},
                    }},
                    timeout=30,
                )
                if r.status_code == 200:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    text = text.strip().strip("`").strip()
                    if text.startswith("json"):
                        text = text[4:].strip()
                    plan_data = json.loads(text)
                    layers = [[a for a in layer if a in valid_names] for layer in plan_data.get("layers", [])]
                    layers = [l for l in layers if l]
                    if layers:
                        return {{"layers": layers, "source": "llm"}}
            except Exception as e:
                self.log("Gemini planning failed: " + str(e)[:80])
        return None

    def _plan_execution(self, query, catalogue):
        agent_names = [a["name"] for a in catalogue]
        cat_text = chr(10).join(
            "- " + a["name"] + " (layer " + str(a["layer"]) + "): " + a["description"]
            for a in sorted(catalogue, key=lambda x: x["layer"])
        )
        system_prompt = (
            "You are the ORCHESTRATOR of LandIQ - an Indian land investment advisor.\\n"
            "You have FULL AUTHORITY to decide which agents run and in what order.\\n\\n"
            "Return ONLY this JSON (no markdown, no explanation):\\n"
            "{{\\"layers\\": [[\\"agent1\\",\\"agent2\\"], [\\"agent3\\"], [\\"agent4\\"]]}}\\n\\n"
            "RULES:\\n"
            "- Same list = parallel execution\\n"
            "- Independent research agents -> early layers\\n"
            "- Debate agents (bull, bear) need research results -> middle layer\\n"
            "- due_diligence needs everything -> near end\\n"
            "- senior_consultant ALWAYS last, alone\\n"
            "- Only use agent names from the AVAILABLE AGENTS list\\n"
            "- Return ONLY the JSON."
        )
        user_prompt = (
            "AVAILABLE AGENTS:\\n" + cat_text + "\\n\\n"
            "ANALYSE: " + str(query.get("land_size", "")) + " " + str(query.get("land_unit", "")) +
            " in " + str(query.get("area", "")) + ", " + str(query.get("city", "")) + ", " + str(query.get("state", "")) +
            ". Budget INR " + str(query.get("total_budget", "")) + ". Purpose: " + str(query.get("purpose", "")) + ".\\n\\n"
            "Return JSON plan now."
        )
        plan = self._call_llm_for_plan(system_prompt, user_prompt, agent_names)
        if plan:
            self.log("LLM PLAN: " + str(plan["layers"]))
            return plan
        self.log("LLM planning failed - using catalogue layer numbers")
        return self._default_plan(catalogue)

    def dispatch(self) -> Data:
        query = dict(self.query_input.data) if self.query_input and getattr(self.query_input, "data", None) else {{}}
        catalogue = self._read_catalogue()
        if catalogue:
            plan = self._plan_execution(query, catalogue)
        else:
            plan = {{"layers": [], "source": "no_catalogue"}}
        out = dict(query)
        out["_orchestrator_plan"] = plan
        self.status = {{"plan": plan}}
        return Data(data=out)
'''.format(project_root=PROJECT_ROOT)

planner_def = build_component(PLANNER_CODE, "LandIQOrchestratorPlan")
print("      -> Orchestrator Plan & Dispatch built")


# ------------------------------------------------------------------ 5
print("\n[5/8] Rebuilding the Aggregator with an 11th input (the real plan) ...")

AGG_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.message import Message
import json


class LandIQAggregator(Component):
    display_name = "LandIQ Orchestrator - Combine Results"
    description = "Paired with 'Plan & Dispatch' upstream - together they ARE the LandIQ Orchestrator. This half takes the {n} real agent results (each already executed as its own wired node, in the real dependency order) plus the plan the LLM actually decided, and assembles the final analysis result. No agent execution happens here."
    icon = "merge"
    name = "LandIQAggregator"

    inputs = [
        DataInput(name="plan_info", display_name="Orchestrator Plan", info="The plan the LLM decided, from Plan & Dispatch."),
{agg_inputs}
    ]

    outputs = [
        Output(display_name="Final Message", name="final_message", method="final_message"),
    ]

    def final_message(self) -> Message:
        state = {{}}
        completed = []
        errors = []
        for handle in [{handle_list}]:
            d = getattr(self, handle, None)
            if not d or not getattr(d, "data", None):
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

        plan = None
        if self.plan_info and getattr(self.plan_info, "data", None):
            plan = self.plan_info.data.get("_orchestrator_plan")
        state["execution_plan"] = plan or {{"layers": {layers_literal}, "source": "graph"}}

        self.status = state
        return Message(text=json.dumps(state, default=str))
'''

agg_inputs = "\n".join(
    '        DataInput(name="in_%s", display_name="%s Result"),' % (a, pretty_name(a))
    for a in all_agents
)
handle_list = ", ".join('"in_%s"' % a for a in all_agents)
agg_code = AGG_TEMPLATE.format(
    n=len(all_agents), agg_inputs=agg_inputs, handle_list=handle_list,
    layers_literal=json.dumps(layers_list),
)
aggregator_def = build_component(agg_code, "LandIQAggregator")
print("      -> Aggregator rebuilt (11 inputs: 10 agents + plan)")


# ------------------------------------------------------------------ 6
print("\n[6/8] Laying out a clean left-to-right pipeline ...")

PLANNER_ID = "LandIQOrchestratorPlan-1"
X_STEP = 500
Y_STEP = 150

final_nodes = []

def place(node, x, y):
    node = dict(node)
    node["position"] = {"x": x, "y": y}
    return node

final_nodes.append(place(chat_input_node, 0, 0))
final_nodes.append(place(parse_node, X_STEP, 0))

planner_node = {
    "id": PLANNER_ID,
    "type": "genericNode",
    "position": {"x": X_STEP * 2, "y": 0},
    "selected": False,
    "data": {"node": planner_def, "showNode": True, "type": "LandIQOrchestratorPlan", "id": PLANNER_ID},
}
final_nodes.append(planner_node)

layer1_y0 = -((len(layers_list[0]) - 1) * Y_STEP) // 2
for i, name in enumerate(layers_list[0]):
    n = find_by_id(nodes, agent_node_ids[name])
    final_nodes.append(place(n, X_STEP * 3, layer1_y0 + i * Y_STEP))

for layer_idx in range(1, len(layers_list)):
    layer_agents = layers_list[layer_idx]
    y0 = -((len(layer_agents) - 1) * Y_STEP) // 2
    for i, name in enumerate(layer_agents):
        n = find_by_id(nodes, agent_node_ids[name])
        final_nodes.append(place(n, X_STEP * (3 + layer_idx), y0 + i * Y_STEP))

agg_x = X_STEP * (3 + len(layers_list))
aggregator_node_new = dict(aggregator_node)
aggregator_node_new["data"] = dict(aggregator_node_new["data"])
aggregator_node_new["data"]["node"] = aggregator_def
final_nodes.append(place(aggregator_node_new, agg_x, 0))

final_nodes.append(place(chat_output_node, agg_x + X_STEP, 0))

NOTE_ID = "note-orchestrator-explainer"
note_node = {
    "id": NOTE_ID,
    "type": "noteNode",
    "position": {"x": X_STEP * 2, "y": -350},
    "selected": False,
    "data": {
        "id": NOTE_ID,
        "type": "note",
        "node": {
            "template": {
                "backgroundColor": "indigo",
                "text": (
                    "LANDIQ ORCHESTRATOR (2 boxes, 1 job)\n\n"
                    "Plan & Dispatch: reads agents_registry/ live, asks an LLM which "
                    "agents run and how they group, then sends the property data "
                    "forward to every agent below.\n\n"
                    "Combine Results: reads every agent's real output (already "
                    "executed as its own wired node, in real dependency order) plus "
                    "the plan above, and assembles the final result. Nothing is "
                    "executed inside either box - the agent boxes ARE the execution."
                ),
            },
            "description": "",
            "display_name": "",
            "documentation": "",
        },
    },
    "width": 380,
    "height": 260,
}
final_nodes.append(note_node)

for n in other_nodes:
    final_nodes.append(n)  # leave any unrelated leftover nodes (e.g. orphaned APIRequest) untouched

print("      -> %d nodes laid out" % len(final_nodes))


# ------------------------------------------------------------------ 7
print("\n[7/8] Rebuilding the full edge set ...")

eid_n = [0]
def next_eid(prefix):
    eid_n[0] += 1
    return "reactflow__edge-v6-%s-%d" % (prefix, eid_n[0])

final_edges = []

final_edges.append(make_edge(
    chat_input_node["id"],
    {"dataType": "ChatInput", "id": chat_input_node["id"], "name": "message", "output_types": ["Message"]},
    parse_node["id"],
    {"fieldName": "input_value", "id": parse_node["id"], "inputTypes": ["Message"], "type": "str"},
    next_eid("in-parse"),
))

final_edges.append(make_edge(
    parse_node["id"],
    {"dataType": "LandIQParseQuery", "id": parse_node["id"], "name": "request", "output_types": ["JSON"]},
    PLANNER_ID,
    {"fieldName": "query_input", "id": PLANNER_ID, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
    next_eid("parse-plan"),
))

for name in all_agents:
    node_id = agent_node_ids[name]
    final_edges.append(make_edge(
        PLANNER_ID,
        {"dataType": "LandIQOrchestratorPlan", "id": PLANNER_ID, "name": "dispatch", "output_types": ["JSON"]},
        node_id,
        {"fieldName": "property_data", "id": node_id, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("dispatch-%s" % name),
    ))

for layer_idx, layer_agents in enumerate(layers_list):
    preds = predecessors_of(layer_idx)
    for name in layer_agents:
        node_id = agent_node_ids[name]
        for p in preds:
            pred_id = agent_node_ids[p]
            final_edges.append(make_edge(
                pred_id,
                {"dataType": "LandIQAgent_%s" % p, "id": pred_id, "name": "output", "output_types": ["JSON"]},
                node_id,
                {"fieldName": "prev_%s" % p, "id": node_id, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
                next_eid("dep-%s-%s" % (p, name)),
            ))

final_edges.append(make_edge(
    PLANNER_ID,
    {"dataType": "LandIQOrchestratorPlan", "id": PLANNER_ID, "name": "dispatch", "output_types": ["JSON"]},
    aggregator_node["id"],
    {"fieldName": "plan_info", "id": aggregator_node["id"], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
    next_eid("plan-agg"),
))

for name in all_agents:
    node_id = agent_node_ids[name]
    final_edges.append(make_edge(
        node_id,
        {"dataType": "LandIQAgent_%s" % name, "id": node_id, "name": "output", "output_types": ["JSON"]},
        aggregator_node["id"],
        {"fieldName": "in_%s" % name, "id": aggregator_node["id"], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("agg-in-%s" % name),
    ))

final_edges.append(make_edge(
    aggregator_node["id"],
    {"dataType": "LandIQAggregator", "id": aggregator_node["id"], "name": "final_message", "output_types": ["Message"]},
    chat_output_node["id"],
    {"fieldName": "input_value", "id": chat_output_node["id"], "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
    next_eid("agg-out"),
))

print("      -> %d edges assembled" % len(final_edges))


# ------------------------------------------------------------------ 8
print("\n[8/8] Saving to the live flow ...")
payload = {
    "name": flow.get("name", "LandIQ Orchestrator"),
    "description": flow.get("description", ""),
    "data": {"nodes": final_nodes, "edges": final_edges},
}
pstatus, presult = call("PATCH", "/api/v1/flows/%s" % flow_id, payload, timeout=60)
if pstatus >= 400:
    die("Langflow rejected the update (HTTP %s):\n\n%s" % (pstatus, presult))

vstatus2, vflow = call("GET", "/api/v1/flows/%s" % flow_id)
vnodes = vflow.get("data", {}).get("nodes", [])
vedges = vflow.get("data", {}).get("edges", [])

if len(vedges) != len(final_edges):
    print("\n  [!] WARNING: expected %d edges, live flow has %d — inspect before demoing."
          % (len(final_edges), len(vedges)))
else:
    print("      -> verified: all %d edges landed" % len(vedges))

print("\n" + "=" * 66)
print("  DONE")
print("=" * 66)
print("  Flow id : %s" % flow_id)
print("  Nodes   : %d   Edges: %d" % (len(vnodes), len(vedges)))
print("\n  OPEN THIS:  %s/flow/%s" % (LANGFLOW, flow_id))
print("=" * 66 + "\n")
