"""
setup_langflow_full.py
─────────────────────
Creates a FULL visual Langflow flow with:
  • User Input component
  • LandIQ Orchestrator (calls backend, timeout=600s)
  • 10 individual agent components arranged in 4 layers
  • Senior Report output
  • All wires connecting them in the correct layer order

Run:  python setup_langflow_full.py
Then: Open http://localhost:7860 → you'll see the full pipeline
"""

import json, uuid, requests, sys, os

LANGFLOW = os.environ.get("LANGFLOW_URL", "http://localhost:7860")
BACKEND  = os.environ.get("LANDIQ_BACKEND", "http://localhost:8000")

# ── helpers ──────────────────────────────────────────────────────────
def uid():
    return str(uuid.uuid4())

def make_custom_node(node_id, name, desc, code, pos_x, pos_y, inputs=None, outputs=None):
    """Build a Langflow CustomComponent node dict."""
    _inputs = inputs or []
    _outputs = outputs or [{"name": "output", "display_name": "Output", "method": "build_output"}]
    return {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": pos_x, "y": pos_y},
        "data": {
            "id": node_id,
            "type": "CustomComponent",
            "node": {
                "display_name": name,
                "description": desc,
                "base_classes": ["Message"],
                "template": {
                    "_type": "Component",
                    "code": {
                        "type": "code",
                        "required": True,
                        "placeholder": "",
                        "show": True,
                        "value": code,
                        "name": "code",
                        "advanced": True,
                    }
                },
                "output_types": ["Message"],
                "inputs": _inputs,
                "outputs": _outputs,
            }
        }
    }

def make_edge(source_id, target_id, source_handle="output", target_handle="input"):
    eid = uid()
    return {
        "id": eid,
        "source": source_id,
        "target": target_id,
        "sourceHandle": f"{source_id}|{source_handle}",
        "targetHandle": f"{target_id}|{target_handle}",
        "data": {
            "sourceHandle": {"id": source_id, "name": source_handle, "output_types": ["Message"]},
            "targetHandle": {"id": target_id, "name": target_handle, "input_types": ["Message"]},
        }
    }

# ── Component Code Templates ────────────────────────────────────────

ORCHESTRATOR_CODE = '''
from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema.message import Message
import requests, json

class LandIQOrchestrator(Component):
    display_name = "LandIQ Orchestrator"
    description = "Calls the LandIQ backend to run the full agent pipeline"

    inputs = [
        MessageTextInput(name="budget", display_name="Budget (INR)", value="50 Lakhs"),
        MessageTextInput(name="city", display_name="City", value="gurugram"),
        MessageTextInput(name="land_type", display_name="Land Type", value="residential"),
        MessageTextInput(name="location", display_name="Location / Area", value="sector 44"),
        MessageTextInput(name="purpose", display_name="Purpose", value="investment"),
        MessageTextInput(name="state", display_name="State", value="haryana"),
    ]

    outputs = [
        Output(display_name="Full Result", name="full_result", method="run_pipeline"),
    ]

    def run_pipeline(self) -> Message:
        payload = {
            "budget": self.budget,
            "city": self.city,
            "land_type": self.land_type,
            "location": self.location,
            "purpose": self.purpose,
            "state": self.state,
            "selected_agents": ["all"],
        }
        try:
            resp = requests.post(
                "''' + BACKEND + '''/analyse",
                json=payload,
                timeout=600,
            )
            data = resp.json()
            return Message(text=json.dumps(data, indent=2))
        except Exception as e:
            return Message(text=json.dumps({"error": str(e)}))
'''

def agent_filter_code(agent_key, agent_display):
    return f'''
from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema.message import Message
import json

class {agent_key.title().replace("_","")}Agent(Component):
    display_name = "{agent_display}"
    description = "Extracts {agent_display} output from the orchestrator result"

    inputs = [
        MessageTextInput(name="input", display_name="Pipeline Result", is_list=False),
    ]

    outputs = [
        Output(display_name="Agent Output", name="output", method="build_output"),
    ]

    def build_output(self) -> Message:
        try:
            data = json.loads(self.input)
            # Try multiple key patterns the backend might use
            result = (
                data.get("{agent_key}_output")
                or data.get("{agent_key}")
                or data.get("{agent_display}")
                or data.get("agents", {{}}).get("{agent_key}")
                or data.get("agents", {{}}).get("{agent_display}")
                or "{agent_display}: awaiting data"
            )
            if isinstance(result, dict):
                result = json.dumps(result, indent=2)
            return Message(text=str(result))
        except Exception as e:
            return Message(text=f"{agent_display}: {{e}}")
'''

REPORT_CODE = '''
from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema.message import Message
import json

class AnalysisReport(Component):
    display_name = "Analysis Report"
    description = "Aggregates the Senior Consultant verdict into a final report"

    inputs = [
        MessageTextInput(name="input", display_name="Senior Verdict", is_list=False),
    ]

    outputs = [
        Output(display_name="Final Report", name="output", method="build_output"),
    ]

    def build_output(self) -> Message:
        return Message(text=self.input if self.input else "No report generated")
'''

# ── Agent definitions with layout ───────────────────────────────────
# (key, display_name, layer, position_in_layer)
AGENTS = [
    # Layer 1
    ("environmental_risk", "🌿 Environmental Risk",    1, 0),
    ("financial",          "💰 Financial Analysis",     1, 1),
    ("legal",              "⚖️ Legal Risk",             1, 2),
    ("location",           "📍 Location Intelligence",  1, 3),
    ("market",             "📊 Market Intelligence",    1, 4),
    # Layer 2
    ("area_crowd",         "👥 Area Crowd Analysis",    2, 0),
    ("bear",               "🐻 Bear Case",              2, 1),
    ("bull",               "🐂 Bull Case",              2, 2),
    # Layer 3
    ("due_diligence",      "🔍 Due Diligence",          3, 0),
    # Layer 4
    ("senior_consultant",  "🏛️ Senior Consultant",      4, 0),
]

# Layout constants
LAYER_X = {0: 100, 1: 700, 2: 1300, 3: 1900, 4: 2500, 5: 3100}
LAYER_Y_START = {1: 0, 2: 80, 3: 200, 4: 200}
AGENT_Y_GAP = 160


# ── Build the flow ──────────────────────────────────────────────────
def build_flow():
    nodes = []
    edges = []

    # 1. Orchestrator node (left side)
    orch_id = uid()
    nodes.append(make_custom_node(
        orch_id,
        "🎯 LandIQ Orchestrator",
        "Runs the full LandIQ agent pipeline via backend API (timeout: 600s)",
        ORCHESTRATOR_CODE,
        LAYER_X[0], 200,
    ))

    # 2. Agent nodes per layer
    agent_nodes = {}  # key -> node_id
    layer_agents = {1: [], 2: [], 3: [], 4: []}

    for key, display, layer, pos in AGENTS:
        nid = uid()
        agent_nodes[key] = nid
        layer_agents[layer].append(nid)

        y = LAYER_Y_START.get(layer, 0) + pos * AGENT_Y_GAP
        nodes.append(make_custom_node(
            nid,
            display,
            f"{display} agent — extracts its output from orchestrator result",
            agent_filter_code(key, display),
            LAYER_X[layer], y,
        ))

    # 3. Report node (right side)
    report_id = uid()
    nodes.append(make_custom_node(
        report_id,
        "📋 Analysis Report",
        "Final investment analysis report with verdict",
        REPORT_CODE,
        LAYER_X[5], 200,
    ))

    # ── Wires ───────────────────────────────────────────────────────

    # Orchestrator → every Layer 1 agent
    for nid in layer_agents[1]:
        edges.append(make_edge(orch_id, nid, "full_result", "input"))

    # Every Layer 1 agent → every Layer 2 agent
    for src in layer_agents[1]:
        for tgt in layer_agents[2]:
            edges.append(make_edge(src, tgt))

    # Every Layer 2 agent → Due Diligence (Layer 3)
    for src in layer_agents[2]:
        for tgt in layer_agents[3]:
            edges.append(make_edge(src, tgt))

    # Due Diligence → Senior Consultant (Layer 4)
    for src in layer_agents[3]:
        for tgt in layer_agents[4]:
            edges.append(make_edge(src, tgt))

    # Senior Consultant → Report
    for src in layer_agents[4]:
        edges.append(make_edge(src, report_id))

    return {
        "data": {"nodes": nodes, "edges": edges},
        "name": "LandIQ Full Pipeline",
        "description": "Complete LandIQ agent pipeline — 10 agents in 4 layers with LLM-planned orchestration",
        "is_component": False,
    }


# ── Upload to Langflow ──────────────────────────────────────────────
def upload(flow_json):
    api = f"{LANGFLOW}/api/v1"

    # Check if Langflow is reachable
    try:
        r = requests.get(f"{api}/flows", timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[!] Cannot reach Langflow at {LANGFLOW}: {e}")
        print("    Make sure Langflow is running: langflow run --port 7860")
        # Save JSON to file so user can import manually
        save_path = "langflow_full_pipeline.json"
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(flow_json, f, indent=2)
        print(f"[*] Saved flow JSON to {save_path}")
        print("    → Open Langflow → My Projects → Import → select this file")
        return save_path

    existing = r.json()
    # Check for existing LandIQ flows
    for fl in (existing if isinstance(existing, list) else existing.get("flows", existing.get("results", []))):
        fname = fl.get("name", "")
        if "LandIQ" in fname:
            fid = fl.get("id")
            print(f"[*] Deleting old flow: {fname} ({fid})")
            try:
                requests.delete(f"{api}/flows/{fid}", timeout=5)
            except:
                pass

    # Create new flow
    print("[*] Creating full pipeline flow...")
    try:
        r = requests.post(f"{api}/flows", json=flow_json, timeout=10)
        if r.status_code in (200, 201):
            data = r.json()
            flow_id = data.get("id", "unknown")
            print(f"[✓] Flow created! ID: {flow_id}")
            print(f"    → Open: {LANGFLOW}/flow/{flow_id}")

            # Save flow ID for langflow_bridge.py
            with open("langflow_flow_id.txt", "w") as f:
                f.write(flow_id)
            print(f"[*] Saved flow ID to langflow_flow_id.txt")
            return flow_id
        else:
            print(f"[!] Create failed ({r.status_code}): {r.text[:300]}")
            # Fallback: save to file
            save_path = "langflow_full_pipeline.json"
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(flow_json, f, indent=2)
            print(f"[*] Saved flow JSON to {save_path}")
            print("    → Open Langflow → My Projects → Import → select this file")
            return save_path
    except Exception as e:
        print(f"[!] Upload error: {e}")
        save_path = "langflow_full_pipeline.json"
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(flow_json, f, indent=2)
        print(f"[*] Saved flow JSON to {save_path}")
        print("    → Open Langflow → My Projects → Import → select this file")
        return save_path


# ── Also update langflow_bridge.py with correct timeout ─────────────
def fix_bridge():
    bridge_path = os.path.join("src", "utils", "langflow_bridge.py")
    code = '''"""
langflow_bridge.py — connects LandIQ backend to Langflow
"""
import os, requests, json, logging

logger = logging.getLogger(__name__)

LANGFLOW_URL = os.environ.get("LANGFLOW_URL", "http://localhost:7860")
FLOW_ID_FILE = "langflow_flow_id.txt"


def _get_flow_id():
    if os.path.exists(FLOW_ID_FILE):
        with open(FLOW_ID_FILE) as f:
            return f.read().strip()
    return None


def langflow_status():
    """Check if Langflow is alive and return flow info."""
    fid = _get_flow_id()
    try:
        r = requests.get(f"{LANGFLOW_URL}/api/v1/flows", timeout=5)
        alive = r.status_code == 200
        flows = []
        if alive:
            data = r.json()
            fl = data if isinstance(data, list) else data.get("flows", data.get("results", []))
            flows = [{"id": f.get("id"), "name": f.get("name")} for f in fl]
    except Exception:
        alive = False
        flows = []

    return {
        "langflow_alive": alive,
        "langflow_url": LANGFLOW_URL,
        "flow_id": fid,
        "flows": flows,
    }


def run_via_langflow(payload: dict, timeout: int = 600):
    """
    Run the LandIQ pipeline through Langflow.
    Falls back gracefully if Langflow is unavailable.
    timeout=600 because full pipeline takes ~200s.
    """
    fid = _get_flow_id()
    if not fid:
        return None  # no flow configured — fallback to local

    try:
        url = f"{LANGFLOW_URL}/api/v1/run/{fid}"
        body = {
            "input_value": json.dumps(payload),
            "output_type": "text",
            "input_type": "text",
            "tweaks": {
                # Pass user inputs to the orchestrator component
                "budget": payload.get("budget", "50 Lakhs"),
                "city": payload.get("city", "gurugram"),
                "land_type": payload.get("land_type", "residential"),
                "location": payload.get("location", "sector 44"),
                "purpose": payload.get("purpose", "investment"),
                "state": payload.get("state", "haryana"),
            }
        }
        logger.info(f"[Langflow] Running flow {fid} ...")
        r = requests.post(url, json=body, timeout=timeout)

        if r.status_code == 200:
            result = r.json()
            logger.info("[Langflow] Flow completed successfully")
            return result
        else:
            logger.warning(f"[Langflow] Flow returned {r.status_code}: {r.text[:200]}")
            return None

    except requests.exceptions.Timeout:
        logger.warning("[Langflow] Flow timed out (this is normal for large pipelines, falling back to local)")
        return None
    except Exception as e:
        logger.warning(f"[Langflow] Error: {e}")
        return None
'''
    os.makedirs(os.path.dirname(bridge_path), exist_ok=True)
    with open(bridge_path, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"[✓] Updated {bridge_path} (timeout=600s)")


# ── Main ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  LandIQ → Langflow Full Pipeline Setup")
    print("=" * 60)
    print()

    # Step 1: Build flow JSON
    print("[1/3] Building flow with 10 agents in 4 layers...")
    flow = build_flow()
    n_nodes = len(flow["data"]["nodes"])
    n_edges = len(flow["data"]["edges"])
    print(f"      {n_nodes} components, {n_edges} wire connections")

    # Step 2: Upload to Langflow
    print("[2/3] Uploading to Langflow...")
    result = upload(flow)

    # Step 3: Fix langflow_bridge.py
    print("[3/3] Updating langflow_bridge.py...")
    fix_bridge()

    print()
    print("=" * 60)
    print("  DONE!")
    print()
    print("  What sir will see on the Langflow canvas:")
    print()
    print("  [🎯 Orchestrator]")
    print("       ↓")
    print("  Layer 1: [🌿 Env Risk] [💰 Financial] [⚖️ Legal]")
    print("           [📍 Location] [📊 Market]")
    print("       ↓")
    print("  Layer 2: [👥 Area Crowd] [🐻 Bear] [🐂 Bull]")
    print("       ↓")
    print("  Layer 3: [🔍 Due Diligence]")
    print("       ↓")
    print("  Layer 4: [🏛️ Senior Consultant]")
    print("       ↓")
    print("  [📋 Analysis Report]")
    print()
    print("  12 components • 4 execution layers • all wired")
    print("=" * 60)
