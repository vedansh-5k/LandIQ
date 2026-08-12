"""
build_landiq_flow_v3.py
------------------------
Rebuilds the LandIQ Langflow orchestrator flow so it is REAL, not decorative.

What was wrong before (build_landiq_flow.py / the live flow):
  * ChatInput was never wired to anything - user input never reached any node.
  * Every "agent" node did a hardcoded GET to /registry/agents/{name}, which
    only returns the agent's static markdown definition. No LLM was ever
    called, no property data was ever sent, nothing was ever analysed.

What this script builds instead (same flow_id, nothing else touched):

    ChatInput  --(message)-->  LandIQParseQuery  --(request/Data)-->
        APIRequest (POST /internal/run-full-pipeline)  --(data)-->  ChatOutput

  * LandIQParseQuery is a small custom Python component (validated live
    against this Langflow install via /api/v1/validate/code and
    /api/v1/custom_component - not hand-guessed). It turns whatever JSON the
    user pastes into ChatInput into a full LandIQ property-analysis request,
    filling safe defaults for anything they leave out.
  * The APIRequest node POSTs that request to /internal/run-full-pipeline,
    which (after the langflow_routes.py fix) calls the exact same
    `analyse_land` function the normal /analyse endpoint uses - same LLM
    planner, same dynamic agents_registry discovery, same guardrails, same
    MLflow logging. Langflow is a real trigger for the real orchestrator,
    not a second implementation of it.
  * Nothing here is agent-name-hardcoded: the backend decides which agents
    run and in what order, live, via the LLM planner.

Needs running first:
  1. Langflow, launched via start_langflow.ps1 (SSRF protection OFF for
     127.0.0.1 - see that script). Default: http://127.0.0.1:7860
  2. LandIQ backend: python api.py  (port 8000)

Usage:
    python build_landiq_flow_v3.py
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


# ------------------------------------------------------------------ 1
print("\n[1/6] Locating the LandIQ flow ...")
if not FLOW_ID_FILE.exists():
    die("langflow_flow_id.txt not found. Run setup_langflow.py first.")
flow_id = FLOW_ID_FILE.read_text(encoding="utf-8").strip()

status, flow = call("GET", "/api/v1/flows/%s" % flow_id)
if status >= 400 or not flow.get("data"):
    die("Could not load flow %s (HTTP %s): %s" % (flow_id, status, flow))
print("      -> loaded '%s' (%d nodes)" % (flow.get("name"), len(flow["data"].get("nodes", []))))


# ------------------------------------------------------------------ 2
print("\n[2/6] Extracting reusable node templates (ChatInput / APIRequest / ChatOutput) ...")


def find_by_type(nodes, type_name):
    for n in nodes:
        if n.get("data", {}).get("type") == type_name:
            return n
    return None


nodes = flow["data"].get("nodes", [])
chat_in = find_by_type(nodes, "ChatInput")
api_req = find_by_type(nodes, "APIRequest")
chat_out = find_by_type(nodes, "ChatOutput")

if not (chat_in and api_req and chat_out):
    die("Flow is missing a ChatInput / APIRequest / ChatOutput node to clone from.\n"
        "    Open the flow in Langflow, drag one of each onto the canvas, SAVE, rerun.")
print("      -> found ChatInput=%s APIRequest=%s ChatOutput=%s" % (chat_in["id"], api_req["id"], chat_out["id"]))


# ------------------------------------------------------------------ 3
print("\n[3/6] Building + validating the LandIQParseQuery custom component ...")

PARSE_COMPONENT_CODE = '''from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.data import Data


class LandIQParseQuery(Component):
    display_name = "LandIQ Parse Query"
    description = (
        "Parses the chat JSON into a full LandIQ property-analysis request, "
        "filling safe defaults for any fields the user did not send."
    )
    icon = "code"
    name = "LandIQParseQuery"

    inputs = [
        MessageTextInput(
            name="input_value",
            display_name="Query JSON",
            info="JSON describing the property (area, city, state, budget, purpose, ...).",
            value=(
                '{"area":"Whitefield","city":"Bangalore","state":"Karnataka",'
                '"total_budget":5000000,"purpose":"investment"}'
            ),
            tool_mode=True,
        ),
    ]

    outputs = [
        Output(display_name="Request", name="request", method="build_request"),
    ]

    def build_request(self) -> Data:
        import json

        defaults = {
            "state": "Karnataka", "city": "Bangalore", "area": "Whitefield",
            "pincode": "", "land_size": 2400, "land_unit": "sq ft",
            "land_type": "residential", "has_title_deed": True,
            "total_budget": 5000000, "construction_budget": 0,
            "taking_loan": False, "loan_amount": 0, "loan_interest_rate": 0,
            "purpose": "investment", "timeline_years": 5,
            "monthly_income_expectation": 0, "risk_tolerance": "moderate",
            "selected_agents": ["all"], "caveman_mode": False,
            "caveman_level": "full", "selected_config": None,
            "guardrail_mode": "none", "guardrail_config": None,
        }

        try:
            parsed = json.loads(self.input_value)
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception:
            parsed = {}

        merged = dict(defaults)
        merged.update({k: v for k, v in parsed.items() if v is not None})

        self.status = merged
        return Data(data=merged)
'''

vstatus, vresult = call("POST", "/api/v1/validate/code", {"code": PARSE_COMPONENT_CODE})
if vstatus >= 400 or vresult.get("imports", {}).get("errors") or vresult.get("function", {}).get("errors"):
    die("LandIQParseQuery failed validation: %s" % vresult)
print("      -> code validates cleanly against this Langflow install")

cstatus, cresult = call("GET", "/api/v1/all")
if cstatus >= 400:
    die("Could not fetch component registry (HTTP %s)" % cstatus)
custom_template = cresult["custom_component"]["CustomComponent"]

bstatus, bresult = call("POST", "/api/v1/custom_component",
                         {"code": PARSE_COMPONENT_CODE, "frontend_node": custom_template})
if bstatus >= 400:
    die("Could not build LandIQParseQuery component (HTTP %s): %s" % (bstatus, bresult))
parse_node_template = bresult["data"]
parse_node_template["template"]["input_value"]["value"] = (
    '{"area":"Whitefield","city":"Bangalore","state":"Karnataka",'
    '"total_budget":5000000,"purpose":"investment"}'
)
print("      -> LandIQParseQuery component built")


# ------------------------------------------------------------------ 4
print("\n[4/6] Assembling the 4-node flow ...")

PARSE_ID = "LandIQParseQuery-1"
REQ_ID = "APIRequest-1"
OUT_ID = "ChatOutput-1"
IN_ID = chat_in["id"]  # reuse the existing ChatInput node id/wiring untouched


def clone(node, new_id, x, y, display=None):
    import copy
    c = copy.deepcopy(node)
    c["id"] = new_id
    c["data"]["id"] = new_id
    c["position"] = {"x": x, "y": y}
    c.pop("positionAbsolute", None)
    c.pop("dragging", None)
    c["selected"] = False
    if display:
        c["data"]["node"]["display_name"] = display
    return c


def handle_str(d):
    # Langflow encodes edge handle JSON using U+0153 in place of the quote
    # character (matches every handle already saved in this flow).
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


new_chat_in = clone(chat_in, IN_ID, 60, 0, display="LandIQ Query")

new_parse = {
    "id": PARSE_ID,
    "type": "genericNode",
    "position": {"x": 460, "y": 0},
    "selected": False,
    "data": {"node": parse_node_template, "showNode": True, "type": "LandIQParseQuery", "id": PARSE_ID},
}

new_api = clone(api_req, REQ_ID, 900, 0, display="LandIQ Full Pipeline")
tpl = new_api["data"]["node"]["template"]
tpl["method"]["value"] = "POST"
tpl["mode"]["value"] = "URL"
tpl["url_input"]["value"] = BACKEND + "/internal/run-full-pipeline"
tpl["timeout"]["value"] = 280
tpl["body"]["value"] = []  # driven by the incoming edge instead of a static value

new_chat_out = clone(chat_out, OUT_ID, 1380, 0, display="LandIQ Result")

edges = [
    make_edge(
        IN_ID,
        {"dataType": "ChatInput", "id": IN_ID, "name": "message", "output_types": ["Message"]},
        PARSE_ID,
        {"fieldName": "input_value", "id": PARSE_ID, "inputTypes": ["Message"], "type": "str"},
        "reactflow__edge-landiq-1",
    ),
    make_edge(
        PARSE_ID,
        {"dataType": "LandIQParseQuery", "id": PARSE_ID, "name": "request", "output_types": ["JSON"]},
        REQ_ID,
        {"fieldName": "body", "id": REQ_ID, "inputTypes": ["Data", "JSON"], "type": "other"},
        "reactflow__edge-landiq-2",
    ),
    make_edge(
        REQ_ID,
        {"dataType": "APIRequest", "id": REQ_ID, "name": "data", "output_types": ["JSON"]},
        OUT_ID,
        {"fieldName": "input_value", "id": OUT_ID,
         "inputTypes": ["Data", "JSON", "DataFrame", "Table", "Message"], "type": "other"},
        "reactflow__edge-landiq-3",
    ),
]

new_nodes = [new_chat_in, new_parse, new_api, new_chat_out]
print("      -> %d nodes, %d edges" % (len(new_nodes), len(edges)))


# ------------------------------------------------------------------ 5
print("\n[5/6] Saving the rebuilt flow back to Langflow (same flow_id) ...")
payload = {
    "name": "LandIQ Orchestrator",
    "description": "Real orchestrator trigger: ChatInput -> parse -> POST /internal/run-full-pipeline -> ChatOutput.",
    "data": {"nodes": new_nodes, "edges": edges},
}
pstatus, presult = call("PATCH", "/api/v1/flows/%s" % flow_id, payload, timeout=60)
if pstatus >= 400:
    die("Langflow rejected the update (HTTP %s):\\n\\n%s" % (pstatus, presult))
print("      -> saved")


# ------------------------------------------------------------------ 6
print("\n[6/6] Verifying ...")
vstatus2, vflow = call("GET", "/api/v1/flows/%s" % flow_id)
vnodes = vflow.get("data", {}).get("nodes", [])
vedges = vflow.get("data", {}).get("edges", [])
if len(vnodes) != 4 or len(vedges) != 3:
    die("Flow saved but looks wrong on read-back: %d nodes, %d edges" % (len(vnodes), len(vedges)))

print("\n" + "=" * 66)
print("  DONE")
print("=" * 66)
print("  Flow id : %s" % flow_id)
print("  Nodes   : ChatInput -> LandIQParseQuery -> APIRequest(POST) -> ChatOutput")
print("\n  OPEN THIS:  %s/flow/%s" % (LANGFLOW, flow_id))
print("=" * 66 + "\n")
