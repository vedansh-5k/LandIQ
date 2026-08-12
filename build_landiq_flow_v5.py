"""
build_landiq_flow_v5.py
------------------------
Rebuilds the LandIQ Langflow canvas so the WIRING is the real execution path,
not a decoration next to a hidden black box.

Why this exists: v4 added one visible node per agent, but the edges feeding
each agent's "Property Data" input silently failed to save (root cause: the
source handle declared output_types=["JSON"] while the target handle
declared inputTypes=["Data"] only - zero overlap, so Langflow dropped those
specific edges on save while every other edge in the flow, which happened to
have overlapping types, survived). Meanwhile all 10 agents' real execution
was actually happening inside ONE hidden custom component (LandIQOrchestrator)
that called each agent via its own internal Python loop - correct results,
but nothing on the canvas showed it, which is exactly what looked hardcoded.

What this script does (backend + agents_registry untouched, only the LIVE
Langflow flow's nodes/edges change):

  1. Reads each agent's real `layer:` from agents_registry/*/AGENT.md - the
     SAME source of truth the local orchestrator and the old Langflow
     component both already used. Nothing here is a hardcoded agent list.

  2. Layer 1 agents (independent research) keep their existing single-input
     component untouched - they only need the previously-missing
     LandIQParseQuery -> Property Data edge added, this time with a target
     inputTypes list that actually overlaps the source's output_types.

  3. Layer 2/3/4 agents get REBUILT with one extra DataInput per real
     predecessor (from the layer map above), and their run_agent() merges
     every predecessor's output dict into the state it POSTs to
     /internal/run-single-agent - exactly how dynamic_agent.py's
     _prior_outputs() already expects prior findings to arrive, so the
     backend needs zero changes for this chaining to work.

  4. The old hidden "LandIQ Orchestrator" component (node id kept identical
     so the ChatOutput edge slot doesn't need to move) is replaced with a
     pure LandIQAggregator: 10 DataInputs, zero HTTP calls, zero planning -
     it only combines results that already happened upstream, on-screen.

  5. The 10 decorative per-agent "X Output" ChatOutput boxes from v4 are
     removed. They never executed before (unreachable), and reconnecting them
     without removing them would make the flow serve MULTIPLE independent
     chat outputs per run, which is exactly the kind of ambiguity that broke
     response parsing last time. One flow -> one real chat output
     (LandIQ Result), fed by the aggregator, stays the single source of truth
     api.py already knows how to parse.

  6. Backend/api.py/langflow_bridge.py: UNCHANGED. The aggregator's final
     JSON keeps the exact same shape (location_output, ..., completed_agents,
     execution_plan, orchestrator_source, error_log) that api.py already
     consumes, so nothing downstream needs to change again.

Needs running first:
  1. Langflow (start_langflow.ps1)
  2. LandIQ backend: python run.py (port 8000) - only used to read the live
     agent registry via /registry/agents; agents are NOT run by this script.

Usage:
    python build_landiq_flow_v5.py
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
FLOW_ID_FILE = pathlib.Path("langflow_flow_id.txt")
API_KEY_FILE = pathlib.Path("langflow_api_key.txt")
REGISTRY_DIR = pathlib.Path("agents_registry")

# Broad on purpose: this is exactly the set ChatOutput's own input already
# accepts in this flow, and it's what makes every OTHER edge in the flow
# survive Langflow's save-time type-overlap check. The v4 "in" edges used
# inputTypes=["Data"] only, which didn't overlap the source's
# output_types=["JSON"] and got silently dropped - this is the fix.
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


# ------------------------------------------------------------------ 1
print("\n[1/8] Reading real layer numbers from agents_registry/*/AGENT.md ...")
if not REGISTRY_DIR.is_dir():
    die("agents_registry/ not found - run this from the project root.")

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

if not agent_layers:
    die("No agents found in agents_registry/.")

layers_map = {}
for name, layer in agent_layers.items():
    layers_map.setdefault(layer, []).append(name)
ordered_layer_nums = sorted(layers_map.keys())
layers_list = [sorted(layers_map[n]) for n in ordered_layer_nums]
print("      -> %d agents across %d layers:" % (len(agent_layers), len(layers_list)))
for i, agents_in_layer in enumerate(layers_list, 1):
    print("         Layer %d: %s" % (i, agents_in_layer))

all_agents = [a for layer in layers_list for a in layer]


def predecessors_of(layer_index):
    """All agents in every layer BEFORE layer_index (0-based)."""
    preds = []
    for i in range(layer_index):
        preds.extend(layers_list[i])
    return preds


# ------------------------------------------------------------------ 2
print("\n[2/8] Loading the live flow ...")
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


parse_node = find_by_type(nodes, "LandIQParseQuery")
chat_output_node = find_by_type(nodes, "ChatOutput")  # "LandIQ Result", the only chat output we keep
orchestrator_node = find_by_type(nodes, "LandIQOrchestrator")
if parse_node is None or chat_output_node is None or orchestrator_node is None:
    die("Expected LandIQParseQuery / ChatOutput(LandIQ Result) / LandIQOrchestrator "
        "nodes not found - run build_landiq_flow_v3.py first.")

agent_node_ids = {name: "LandIQAgent_%s" % name for name in all_agents}
missing = [n for n in all_agents if find_by_id(nodes, agent_node_ids[n]) is None]
if missing:
    die("Agent node(s) not found on canvas: %s - run build_landiq_flow_v4.py first." % missing)

print("      -> found Parse, %d agent nodes, Orchestrator, Result" % len(all_agents))


# ------------------------------------------------------------------ 3
print("\n[3/8] Fetching the component registry (for validate/build calls) ...")
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
print("\n[4/8] Rebuilding layer-2/3/4 agent components with real predecessor inputs ...")

AGENT_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.data import Data


class LandIQAgent_{key}(Component):
    display_name = "Agent - {pretty}"
    description = "Runs the real {pretty} agent (agents_registry/{agent}/AGENT.md + SKILL.md) via the LandIQ backend. Layer {layer_num}, depends on: {preds_desc}."
    icon = "brain-circuit"
    name = "LandIQAgent_{key}"

    inputs = [
        DataInput(name="property_data", display_name="Property Data", info="Parsed property JSON from LandIQ Parse Query."),
{extra_inputs}
    ]

    outputs = [
        Output(display_name="{pretty} Output", name="output", method="run_agent"),
    ]

    def run_agent(self) -> Data:
        import httpx

        state = dict(self.property_data.data) if self.property_data else {{}}
{merge_block}
        payload = dict(state)
        payload["agent_name"] = "{agent}"
        payload["location"] = payload.get("area", "")

        try:
            r = httpx.post(
                "{backend}/internal/run-single-agent",
                json=payload,
                timeout=120,
            )
            result = r.json()
        except Exception as e:
            result = {{"error": str(e)}}

        self.status = result
        return Data(data=result)
'''

agent_defs = {}  # name -> built template (only for rebuilt ones)
for layer_idx, layer_agents in enumerate(layers_list):
    preds = predecessors_of(layer_idx)
    if not preds:
        continue  # layer 1: existing component already correct, no rebuild needed
    extra_inputs = "\n".join(
        '        DataInput(name="prev_%s", display_name="%s Result", info="Output from the %s agent (upstream)."),'
        % (p, pretty_name(p), pretty_name(p))
        for p in preds
    )
    merge_block = "\n".join(
        '        _p = self.prev_%s\n'
        '        if _p and getattr(_p, "data", None):\n'
        '            for _k, _v in _p.data.items():\n'
        '                if _k in ("completed_agents", "error_log"):\n'
        '                    state[_k] = (state.get(_k) or []) + (_v if isinstance(_v, list) else [_v])\n'
        '                else:\n'
        '                    state[_k] = _v'
        % p
        for p in preds
    )
    for name in layer_agents:
        code = AGENT_TEMPLATE.format(
            key=name, pretty=pretty_name(name), agent=name, backend=BACKEND,
            layer_num=layer_idx + 1, preds_desc=", ".join(preds) or "none",
            extra_inputs=extra_inputs, merge_block=merge_block,
        )
        agent_defs[name] = build_component(code, "agent '%s'" % name)
        print("      -> %s (layer %d, %d predecessor inputs) rebuilt" % (name, layer_idx + 1, len(preds)))

print("      -> layer 1 agents (%s) left untouched, no rebuild needed"
      % ", ".join(layers_list[0]))


# ------------------------------------------------------------------ 5
print("\n[5/8] Building the LandIQAggregator (replaces the hidden orchestrator) ...")

AGG_TEMPLATE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.message import Message
import json


class LandIQAggregator(Component):
    display_name = "LandIQ Aggregator"
    description = "Combines the results of all {n} real agents - each already executed as its own wired node upstream, in real dependency order - into the final analysis result. No agent execution happens here."
    icon = "merge"
    name = "LandIQAggregator"

    inputs = [
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
        state["execution_plan"] = {{"layers": {layers_literal}, "source": "graph"}}

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
print("      -> LandIQAggregator built (%d inputs)" % len(all_agents))


# ------------------------------------------------------------------ 6
print("\n[6/8] Assembling the new node list ...")


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


agent_out_id = {name: "ChatOutput_%s" % name for name in all_agents}
ORCH_ID = orchestrator_node["id"]

new_nodes = []
for n in nodes:
    node_id = n.get("id")
    node_type = n.get("data", {}).get("type", "")
    if node_id in agent_out_id.values():
        continue  # drop the 10 decorative per-agent output boxes
    if node_id in agent_defs:  # rebuilt layer 2/3/4 agents - swap in new template, same id/position
        n = dict(n)
        n["data"] = dict(n["data"])
        n["data"]["node"] = agent_defs[node_id]
        n["data"]["type"] = "LandIQAgent_%s" % node_id
    if node_id == ORCH_ID:
        n = dict(n)
        n["data"] = dict(n["data"])
        n["data"]["node"] = aggregator_def
        n["data"]["type"] = "LandIQAggregator"
    new_nodes.append(n)

print("      -> %d nodes (was %d, removed %d decorative output boxes)"
      % (len(new_nodes), len(nodes), len(nodes) - len(new_nodes)))


# ------------------------------------------------------------------ 7
print("\n[7/8] Assembling the new edge list ...")

new_edges = [
    e for e in edges
    if e.get("source") not in agent_out_id.values()
    and e.get("target") not in agent_out_id.values()
    and e.get("source") != ORCH_ID
    and e.get("target") != ORCH_ID
]
kept_base = len(new_edges)  # should just be ChatInput -> LandIQParseQuery

eid_n = [0]
def next_eid(prefix):
    eid_n[0] += 1
    return "reactflow__edge-v5-%s-%d" % (prefix, eid_n[0])

for layer_idx, layer_agents in enumerate(layers_list):
    preds = predecessors_of(layer_idx)
    for name in layer_agents:
        node_id = agent_node_ids[name]
        new_edges.append(make_edge(
            parse_node["id"],
            {"dataType": "LandIQParseQuery", "id": parse_node["id"], "name": "request", "output_types": ["JSON"]},
            node_id,
            {"fieldName": "property_data", "id": node_id, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
            next_eid("prop-%s" % name),
        ))
        for p in preds:
            pred_id = agent_node_ids[p]
            new_edges.append(make_edge(
                pred_id,
                {"dataType": "LandIQAgent_%s" % p, "id": pred_id, "name": "output", "output_types": ["JSON"]},
                node_id,
                {"fieldName": "prev_%s" % p, "id": node_id, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
                next_eid("dep-%s-%s" % (p, name)),
            ))

for name in all_agents:
    node_id = agent_node_ids[name]
    new_edges.append(make_edge(
        node_id,
        {"dataType": "LandIQAgent_%s" % name, "id": node_id, "name": "output", "output_types": ["JSON"]},
        ORCH_ID,
        {"fieldName": "in_%s" % name, "id": ORCH_ID, "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
        next_eid("agg-in-%s" % name),
    ))

new_edges.append(make_edge(
    ORCH_ID,
    {"dataType": "LandIQAggregator", "id": ORCH_ID, "name": "final_message", "output_types": ["Message"]},
    chat_output_node["id"],
    {"fieldName": "input_value", "id": chat_output_node["id"],
     "inputTypes": BROAD_INPUT_TYPES, "type": "other"},
    next_eid("agg-out"),
))

print("      -> %d edges (%d kept unchanged + %d new)" % (len(new_edges), kept_base, len(new_edges) - kept_base))


# ------------------------------------------------------------------ 8
print("\n[8/8] Saving to the live flow ...")
payload = {
    "name": flow.get("name", "LandIQ Orchestrator"),
    "description": flow.get("description", ""),
    "data": {"nodes": new_nodes, "edges": new_edges},
}
pstatus, presult = call("PATCH", "/api/v1/flows/%s" % flow_id, payload, timeout=60)
if pstatus >= 400:
    die("Langflow rejected the update (HTTP %s):\n\n%s" % (pstatus, presult))

vstatus2, vflow = call("GET", "/api/v1/flows/%s" % flow_id)
vnodes = vflow.get("data", {}).get("nodes", [])
vedges = vflow.get("data", {}).get("edges", [])

expected_edges = len(new_edges)
if len(vedges) != expected_edges:
    print("\n  [!] WARNING: expected %d edges after save, live flow has %d — "
          "some edges may have been silently dropped again. Inspect before demoing."
          % (expected_edges, len(vedges)))
else:
    print("      -> verified: all %d edges landed" % len(vedges))

print("\n" + "=" * 66)
print("  DONE")
print("=" * 66)
print("  Flow id : %s" % flow_id)
print("  Nodes   : %d   Edges: %d" % (len(vnodes), len(vedges)))
print("  Layers  : %s" % layers_list)
print("\n  OPEN THIS:  %s/flow/%s" % (LANGFLOW, flow_id))
print("=" * 66 + "\n")
