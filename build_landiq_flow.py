"""
build_landiq_flow.py  (v2)
--------------------------
Builds a complete LandIQ canvas inside Langflow - ONE NODE PER REAL AGENT.

Nothing hardcoded:
  * agent list comes live from your backend /registry/agents
  * node JSON is cloned from your own working flow, so it always matches
    your installed Langflow version exactly

Usage:
    python build_landiq_flow.py
    python build_landiq_flow.py <flow-id>      <- if auto-detect misses

Needs running first:
  1. Langflow with SSRF off  (port 7860)
  2. python run.py           (port 8000)
"""

import copy
import json
import pathlib
import re
import sys
import uuid

try:
    import requests
except ImportError:
    import subprocess
    print("[setup] installing requests ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests


LANGFLOW = "http://127.0.0.1:7860"
BACKEND = "http://127.0.0.1:8000"
REGISTRY = pathlib.Path("agents_registry")
FLOW_ID_FILE = pathlib.Path("langflow_flow_id.txt")
NEW_FLOW_NAME = "LandIQ Orchestrator"

CLI_FLOW_ID = sys.argv[1].strip() if len(sys.argv) > 1 else None


def die(msg):
    print("\n" + "=" * 66)
    print("[X] " + msg)
    print("=" * 66 + "\n")
    sys.exit(1)


def sid():
    return uuid.uuid4().hex[:5]


def norm(s):
    return re.sub(r"[^a-z]", "", str(s or "").lower())


# ------------------------------------------------------------------ 1
print("\n[1/6] Getting the agent list ...")
agents = []
try:
    r = requests.get(BACKEND + "/registry/agents", timeout=10)
    if r.status_code == 200:
        agents = [a["name"] for a in r.json().get("agents", [])]
        print("      source: backend /registry/agents")
except Exception:
    pass

if not agents and REGISTRY.exists():
    agents = sorted(p.name for p in REGISTRY.iterdir()
                    if p.is_dir() and not p.name.startswith((".", "_")))
    print("      source: agents_registry/ on disk")

if not agents:
    die("No agents found. Start the backend (python run.py) and rerun.")

print("      -> %d agents" % len(agents))
for a in agents:
    print("         - " + a)


# ------------------------------------------------------------------ 2
print("\n[2/6] Connecting to Langflow ...")
try:
    h = requests.get(LANGFLOW + "/health", timeout=10)
    if h.status_code >= 400:
        die("Langflow answered HTTP %d." % h.status_code)
except Exception as e:
    die("Cannot reach Langflow at %s\n    %s" % (LANGFLOW, e))
print("      -> Langflow is up")


# ------------------------------------------------------------------ 3
print("\n[3/6] Finding a template flow ...")


def load_flow(fid):
    if not fid:
        return None
    try:
        rr = requests.get("%s/api/v1/flows/%s" % (LANGFLOW, fid), timeout=20)
        if rr.status_code >= 400:
            return None
        j = rr.json()
        return j if isinstance(j, dict) and j.get("data") else None
    except Exception:
        return None


def pick(flow, want):
    """Fuzzy-find a node whose type or id looks like `want`."""
    for n in flow["data"].get("nodes", []):
        tag = norm(n.get("data", {}).get("type")) or norm(n.get("id"))
        if want in tag:
            return n
    return None


def describe(flow):
    out = []
    for n in flow["data"].get("nodes", []):
        out.append(n.get("data", {}).get("type") or n.get("id"))
    return out


def usable(flow):
    return bool(flow) and bool(pick(flow, "apirequest")) and bool(pick(flow, "chatoutput"))


src = None
seen = []

for fid in [CLI_FLOW_ID,
            FLOW_ID_FILE.read_text(encoding="utf-8").strip() if FLOW_ID_FILE.exists() else None]:
    cand = load_flow(fid)
    if usable(cand):
        src = cand
        print("      -> using flow: %s" % cand.get("name"))
        break
    elif cand:
        seen.append((cand.get("name"), describe(cand)))

if src is None:
    try:
        lr = requests.get(LANGFLOW + "/api/v1/flows/",
                          params={"get_all": "true", "header_flows": "false"}, timeout=25)
        lst = lr.json()
        if isinstance(lst, dict):
            lst = lst.get("items") or lst.get("flows") or []
        for f in lst:
            cand = f if f.get("data") else load_flow(f.get("id"))
            if usable(cand):
                src = cand
                print("      -> auto-found flow: %s" % cand.get("name"))
                break
            elif cand:
                seen.append((cand.get("name"), describe(cand)))
    except Exception as e:
        print("      (flow list failed: %s)" % e)

if src is None:
    lines = ["No flow with an API Request node + a Chat Output node was found.\n"]
    if seen:
        lines.append("    Flows checked and what they contain:")
        for nm, types in seen:
            lines.append("      - %s : %s" % (nm, ", ".join(types) or "(empty)"))
    else:
        lines.append("    Langflow returned no readable flows.")
    lines.append("\n    Fix: open your flow in Langflow, copy the id from the address bar")
    lines.append("    (the long code after /flow/), then run:")
    lines.append("      python build_landiq_flow.py <that-id>")
    die("\n".join(lines))

api_req = pick(src, "apirequest")
chat_out = pick(src, "chatoutput")
chat_in = pick(src, "chatinput")

edges = src["data"].get("edges", [])
edge_out = next((e for e in edges
                 if e.get("source") == api_req["id"] and e.get("target") == chat_out["id"]), None)
if edge_out is None:
    die("The API Request node is not connected to the Chat Output node.\n"
        "    In Langflow drag API Response -> Chat Output, press SAVE, then rerun.")
print("      -> template node pair verified")


# ------------------------------------------------------------------ 4
print("\n[4/6] Detecting the URL field ...")
template = api_req["data"]["node"]["template"]
url_key = None

for k, v in template.items():
    if not isinstance(v, dict):
        continue
    val = v.get("value")
    if isinstance(val, str) and val.startswith("http"):
        url_key = k
        break
    if isinstance(val, list) and val and isinstance(val[0], str) and val[0].startswith("http"):
        url_key = k
        break

if url_key is None:
    for cand in ("url_input", "urls", "url"):
        if cand in template:
            url_key = cand
            break

if url_key is None:
    die("Could not find the URL field. Type a URL into the API Request node, SAVE, rerun.")
print("      -> URL field is '%s'" % url_key)


def set_url(node, url):
    field = node["data"]["node"]["template"][url_key]
    if isinstance(field.get("value"), list):
        field["value"] = [url]
    else:
        field["value"] = url


# ------------------------------------------------------------------ 5
print("\n[5/6] Building the canvas ...")


def clone_node(node, new_id, x, y, display=None):
    c = copy.deepcopy(node)
    c["id"] = new_id
    c["data"]["id"] = new_id
    c["position"] = {"x": x, "y": y}
    if "positionAbsolute" in c:
        c["positionAbsolute"] = {"x": x, "y": y}
    c["selected"] = False
    if display:
        c["data"]["node"]["display_name"] = display
    return c


def clone_edge(edge, pairs):
    s = json.dumps(edge)
    for old, new in pairs:
        s = s.replace(old, new)
    e = json.loads(s)
    e["id"] = "reactflow__edge-" + sid()
    return e


new_nodes = []
new_edges = []

if chat_in is not None:
    new_nodes.append(clone_node(chat_in, chat_in["id"], 60, 0, display="LandIQ Query"))

Y_STEP = 300
y = -((len(agents) - 1) * Y_STEP) // 2

for name in agents:
    req_id = "APIRequest-" + sid()
    out_id = "ChatOutput-" + sid()
    pretty = name.replace("_", " ").replace("-", " ").title()

    n = clone_node(api_req, req_id, 620, y, display="Agent - " + pretty)
    set_url(n, "%s/registry/agents/%s" % (BACKEND, name))
    o = clone_node(chat_out, out_id, 1180, y, display=pretty + " Output")

    new_nodes.append(n)
    new_nodes.append(o)
    new_edges.append(clone_edge(edge_out, [(api_req["id"], req_id),
                                           (chat_out["id"], out_id)]))
    y += Y_STEP

print("      -> %d nodes, %d edges assembled" % (len(new_nodes), len(new_edges)))


# ------------------------------------------------------------------ 6
print("\n[6/6] Saving new flow to Langflow ...")
payload = {
    "name": NEW_FLOW_NAME,
    "description": "Auto-generated from agents_registry - %d live agents" % len(agents),
    "data": {"nodes": new_nodes, "edges": new_edges},
}
for key in ("folder_id", "project_id"):
    if src.get(key):
        payload[key] = src[key]

resp = requests.post(LANGFLOW + "/api/v1/flows/", json=payload, timeout=60)
if resp.status_code >= 400:
    payload["name"] = "%s %s" % (NEW_FLOW_NAME, sid())
    resp = requests.post(LANGFLOW + "/api/v1/flows/", json=payload, timeout=60)

if resp.status_code >= 400:
    die("Langflow rejected the flow (HTTP %d):\n\n%s" % (resp.status_code, resp.text[:900]))

new_id = resp.json().get("id")
if not new_id:
    die("Flow created but no id returned:\n%s" % resp.text[:400])

FLOW_ID_FILE.write_text(new_id, encoding="utf-8")

print("\n" + "=" * 66)
print("  DONE")
print("=" * 66)
print("  Flow name : %s" % payload["name"])
print("  Flow id   : %s" % new_id)
print("  Agents    : %d" % len(agents))
print("\n  OPEN THIS:  %s/flow/%s" % (LANGFLOW, new_id))
print("=" * 66 + "\n")
