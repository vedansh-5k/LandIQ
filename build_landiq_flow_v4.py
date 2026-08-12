"""
build_landiq_flow_v4.py
------------------------
ADDS one real, visible, editable node per agent to the LandIQ flow, on top
of the working v3 flow. Does NOT remove or touch the existing
ChatInput / LandIQParseQuery / LandIQ Full Pipeline / LandIQ Result nodes -
that path (the real LLM-planned orchestrator) keeps working exactly as is.

New, for each agent found live in agents_registry/ (no hardcoded list):

    LandIQParseQuery --(property data)--> Agent - <Name> --> <Name> Output

Each "Agent - <Name>" node is a small custom Python component that POSTs to
/internal/run-single-agent for THAT agent - a real LLM call using that
agent's actual AGENT.md + SKILL.md, exactly like the local orchestrator
runs it, just triggered one agent at a time so every agent is visible and
individually editable/re-runnable on the canvas.

Needs running first:
  1. Langflow, launched via start_langflow.ps1
  2. LandIQ backend: python run.py  (port 8000)
  3. build_landiq_flow_v3.py already run once (so ChatInput/LandIQParseQuery exist)

Usage:
    python build_landiq_flow_v4.py
"""

import copy
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
    except urllib.error.HTTPError as e:
        raw = e.read()
        status_code = e.code
    else:
        status_code = r.status
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        return status_code, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status_code, {"error": raw.decode("utf-8", "replace")[:1500]}


def backend_get(path, timeout=10):
    req = urllib.request.Request(BACKEND + path, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------------ 1
print("\n[1/6] Getting the live agent list from the backend ...")
try:
    reg = backend_get("/registry/agents")
    agents = [a["name"] for a in reg.get("agents", [])]
except Exception as e:
    die("Could not reach backend /registry/agents (%s). Start `python run.py` first." % e)
if not agents:
    die("No agents found in agents_registry/.")
print("      -> %d agents: %s" % (len(agents), agents))


# ------------------------------------------------------------------ 2
print("\n[2/6] Locating the existing LandIQ flow ...")
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


parse_node = find_by_type(nodes, "LandIQParseQuery")
if parse_node is None:
    die("LandIQParseQuery node not found - run build_landiq_flow_v3.py first.")
existing_agent_ids = {n["id"] for n in nodes if n.get("data", {}).get("type", "").startswith("LandIQAgent_")}
print("      -> loaded '%s' (%d existing nodes, %d already agent nodes)"
      % (flow.get("name"), len(nodes), len(existing_agent_ids)))


# ------------------------------------------------------------------ 3
print("\n[3/6] Fetching the ChatOutput template to clone per-agent outputs ...")
chat_out_template = find_by_type(nodes, "ChatOutput")
if chat_out_template is None:
    die("No ChatOutput node found to clone.")


# ------------------------------------------------------------------ 4
print("\n[4/6] Building + validating one real component per agent ...")

AGENT_COMPONENT_CODE = '''from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, Output
from lfx.schema.data import Data


class LandIQAgent_{key}(Component):
    display_name = "Agent - {pretty}"
    description = "Runs the real {pretty} agent (agents_registry/{agent}/AGENT.md + SKILL.md) via the LandIQ backend."
    icon = "brain-circuit"
    name = "LandIQAgent_{key}"

    inputs = [
        DataInput(
            name="property_data",
            display_name="Property Data",
            info="Parsed property JSON from LandIQ Parse Query.",
        ),
    ]

    outputs = [
        Output(display_name="{pretty} Output", name="output", method="run_agent"),
    ]

    def run_agent(self) -> Data:
        import httpx

        payload = dict(self.property_data.data) if self.property_data else {{}}
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

cstatus, cresult = call("GET", "/api/v1/all")
if cstatus >= 400:
    die("Could not fetch component registry (HTTP %s)" % cstatus)
custom_template = cresult["custom_component"]["CustomComponent"]


def pretty_name(agent_key):
    return agent_key.replace("_", " ").title()


agent_defs = {}
for name in agents:
    key = name
    code = AGENT_COMPONENT_CODE.format(
        key=key, pretty=pretty_name(name), agent=name, backend=BACKEND
    )
    vstatus, vresult = call("POST", "/api/v1/validate/code", {"code": code})
    if vstatus >= 400 or vresult.get("imports", {}).get("errors") or vresult.get("function", {}).get("errors"):
        die("Agent component for '%s' failed validation: %s" % (name, vresult))

    bstatus, bresult = call("POST", "/api/v1/custom_component",
                             {"code": code, "frontend_node": custom_template})
    if bstatus >= 400:
        die("Could not build agent component for '%s' (HTTP %s): %s" % (name, bstatus, bresult))

    agent_defs[name] = bresult["data"]
    print("      -> %s validated + built" % name)


# ------------------------------------------------------------------ 5
print("\n[5/6] Assembling new nodes/edges (existing nodes untouched) ...")


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


new_nodes = []
new_edges = []
Y_STEP = 160
y = -((len(agents) - 1) * Y_STEP) // 2

for name in agents:
    node_id = "LandIQAgent_%s" % name
    out_id = "ChatOutput_%s" % name

    if node_id in existing_agent_ids:
        y += Y_STEP
        continue  # already built in a previous run - don't duplicate

    agent_node = {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": 900, "y": y},
        "selected": False,
        "data": {"node": agent_defs[name], "showNode": True, "type": "LandIQAgent_%s" % name, "id": node_id},
    }

    out_node = copy.deepcopy(chat_out_template)
    out_node["id"] = out_id
    out_node["data"]["id"] = out_id
    out_node["position"] = {"x": 1380, "y": y}
    out_node.pop("positionAbsolute", None)
    out_node.pop("dragging", None)
    out_node["selected"] = False
    out_node["data"]["node"]["display_name"] = pretty_name(name) + " Output"

    new_nodes.append(agent_node)
    new_nodes.append(out_node)

    new_edges.append(make_edge(
        parse_node["id"],
        {"dataType": "LandIQParseQuery", "id": parse_node["id"], "name": "request", "output_types": ["JSON"]},
        node_id,
        {"fieldName": "property_data", "id": node_id, "inputTypes": ["Data"], "type": "other"},
        "reactflow__edge-agent-%s-in" % name,
    ))
    new_edges.append(make_edge(
        node_id,
        {"dataType": "LandIQAgent_%s" % name, "id": node_id, "name": "output", "output_types": ["JSON"]},
        out_id,
        {"fieldName": "input_value", "id": out_id,
         "inputTypes": ["Data", "JSON", "DataFrame", "Table", "Message"], "type": "other"},
        "reactflow__edge-agent-%s-out" % name,
    ))
    y += Y_STEP

print("      -> adding %d nodes, %d edges" % (len(new_nodes), len(new_edges)))
if not new_nodes:
    print("      -> nothing to add, all agent nodes already exist")


# ------------------------------------------------------------------ 6
print("\n[6/6] Saving ...")
payload = {
    "name": flow.get("name", "LandIQ Orchestrator"),
    "description": flow.get("description", ""),
    "data": {"nodes": nodes + new_nodes, "edges": edges + new_edges},
}
pstatus, presult = call("PATCH", "/api/v1/flows/%s" % flow_id, payload, timeout=60)
if pstatus >= 400:
    die("Langflow rejected the update (HTTP %s):\n\n%s" % (pstatus, presult))

vstatus2, vflow = call("GET", "/api/v1/flows/%s" % flow_id)
vnodes = vflow.get("data", {}).get("nodes", [])
vedges = vflow.get("data", {}).get("edges", [])

print("\n" + "=" * 66)
print("  DONE")
print("=" * 66)
print("  Flow id : %s" % flow_id)
print("  Total   : %d nodes, %d edges (%d agents visible)" % (len(vnodes), len(vedges), len(agents)))
print("\n  OPEN THIS:  %s/flow/%s" % (LANGFLOW, flow_id))
print("=" * 66 + "\n")
