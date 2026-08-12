"""
setup_langflow.py
-----------------
Creates (or repairs) the LandIQ orchestration flow inside a running
Langflow instance.

Nothing about the flow is hardcoded:
  * Component templates are downloaded from the *running* Langflow server,
    so the flow is always valid for whichever Langflow version is installed.
  * The planner instructions are generated from the agents that actually
    exist in agents_registry/ at the moment you run this.
  * The model / provider is read from your .env, not baked in.

Run from the project root, with Langflow already running:

    python setup_langflow.py

If the server refuses the programmatic create for any reason, the script
still writes landiq_flow.json which you can drag straight into the
Langflow UI. Either path ends with a working flow.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    from src.utils import langflow_bridge as lf
except Exception as e:  # pragma: no cover
    print("Could not import src/utils/langflow_bridge.py —", e)
    print("Make sure you are running this from the project root.")
    sys.exit(1)


# ── .env loading (same convention as orchestrator_agent.py) ─────────────
def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


load_env()


# ── agent discovery — live, never hardcoded ─────────────────────────────
def discover_agents() -> List[Dict[str, str]]:
    agents: List[Dict[str, str]] = []
    reg = ROOT / "agents_registry"
    if not reg.is_dir():
        return agents

    for folder in sorted(p for p in reg.iterdir() if p.is_dir()):
        if folder.name.startswith((".", "_")):
            continue
        desc = ""
        for fname in ("AGENT.md", "SKILL.md"):
            f = folder / fname
            if f.exists():
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for line in text.splitlines():
                    s = line.strip()
                    if s.lower().startswith("description:"):
                        desc = s.split(":", 1)[1].strip().strip('"')
                        break
                if not desc:
                    for line in text.splitlines():
                        s = line.strip()
                        if s and not s.startswith(("#", "-", "`", "---", "*")):
                            desc = s
                            break
                if desc:
                    break
        agents.append({"name": folder.name, "description": desc[:150]})
    return agents


def build_planner_prompt(agents: List[Dict[str, str]]) -> str:
    lines = [f"- {a['name']}: {a['description'] or 'specialist agent'}" for a in agents]
    roster = "\n".join(lines) if lines else "- (registry empty)"
    return (
        "You are the ORCHESTRATOR of LandIQ, an Indian land investment "
        "advisory system.\n\n"
        "You decide which specialist agents run, and in what order, for each "
        "user query.\n\n"
        "AGENTS CURRENTLY REGISTERED IN LandIQ:\n"
        f"{roster}\n\n"
        "RULES\n"
        "1. Reply with JSON only. No prose, no markdown fences.\n"
        "2. Schema: {\"layers\": [[\"agent\"], [\"agent\",\"agent\"]], "
        "\"reasoning\": \"one short sentence\"}\n"
        "3. Agents inside one inner list run in parallel. Lists run in order.\n"
        "4. Use only agent names from the list above, spelled exactly.\n"
        "5. Independent research agents go in the earliest layer. Agents that "
        "need other agents' findings go later. Any synthesising or "
        "consultant-style agent goes last, alone.\n"
        "6. Skip agents that are irrelevant to the query. Do not pad the plan.\n"
        "7. Keep each parallel layer to at most 4 agents.\n"
    )


# ── Langflow component templates, fetched live ──────────────────────────
def fetch_components() -> Dict[str, Dict[str, Any]]:
    for path in ("/api/v1/all", "/api/v1/all_types"):
        ok, data, err = lf._request("GET", path, timeout=90.0)
        if ok and isinstance(data, dict) and data:
            flat: Dict[str, Dict[str, Any]] = {}
            for category, comps in data.items():
                if not isinstance(comps, dict):
                    continue
                for name, tmpl in comps.items():
                    if isinstance(tmpl, dict):
                        flat.setdefault(name, tmpl)
            if flat:
                print(f"  fetched {len(flat)} component templates from {path}")
                return flat
    print("  could not fetch component templates:", err)
    return {}


def pick(components: Dict[str, Dict[str, Any]], candidates: List[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
    for c in candidates:
        if c in components:
            return c, json.loads(json.dumps(components[c]))
    low = {k.lower(): k for k in components}
    for c in candidates:
        k = low.get(c.lower())
        if k:
            return k, json.loads(json.dumps(components[k]))
    return None


# ── Langflow graph helpers ──────────────────────────────────────────────
def esc(obj: Any) -> str:
    """Langflow encodes handle JSON with œ standing in for a double quote."""
    return json.dumps(obj, separators=(",", ":")).replace('"', "œ")


def new_id(kind: str) -> str:
    return f"{kind}-{uuid.uuid4().hex[:5]}"


def make_node(kind: str, tmpl: Dict[str, Any], node_id: str, x: int, y: int) -> Dict[str, Any]:
    tmpl.setdefault("display_name", kind)
    return {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "data": {"id": node_id, "type": kind, "node": tmpl},
        "width": 320,
        "height": 300,
        "selected": False,
        "dragging": False,
    }


def set_field(node: Dict[str, Any], field: str, value: Any) -> bool:
    tmpl = node["data"]["node"].get("template", {})
    if field in tmpl and isinstance(tmpl[field], dict):
        tmpl[field]["value"] = value
        return True
    return False


def first_output(node: Dict[str, Any]) -> Dict[str, Any]:
    outs = node["data"]["node"].get("outputs") or []
    for o in outs:
        if isinstance(o, dict) and o.get("name"):
            return o
    return {"name": "output", "types": ["Message"]}


def find_input(node: Dict[str, Any], preferred: List[str]) -> Tuple[str, Dict[str, Any]]:
    tmpl = node["data"]["node"].get("template", {})
    for p in preferred:
        f = tmpl.get(p)
        if isinstance(f, dict):
            return p, f
    for name, f in tmpl.items():
        if isinstance(f, dict) and f.get("input_types") and f.get("show", True):
            return name, f
    return preferred[0], {"input_types": ["Message"], "type": "str"}


def make_edge(src: Dict[str, Any], dst: Dict[str, Any], dst_fields: List[str]) -> Dict[str, Any]:
    out = first_output(src)
    field_name, field = find_input(dst, dst_fields)

    source_handle = {
        "dataType": src["data"]["type"],
        "id": src["id"],
        "name": out.get("name"),
        "output_types": out.get("types") or ["Message"],
    }
    target_handle = {
        "fieldName": field_name,
        "id": dst["id"],
        "inputTypes": field.get("input_types") or ["Message"],
        "type": field.get("type") or "str",
    }
    return {
        "id": f"reactflow__edge-{src['id']}-{dst['id']}-{uuid.uuid4().hex[:6]}",
        "source": src["id"],
        "target": dst["id"],
        "sourceHandle": esc(source_handle),
        "targetHandle": esc(target_handle),
        "data": {"sourceHandle": source_handle, "targetHandle": target_handle},
        "className": "",
        "animated": False,
    }


# ── model configuration, read from .env ─────────────────────────────────
def model_settings() -> Dict[str, str]:
    if os.getenv("GROQ_API_KEY"):
        return {
            "provider": "Groq",
            "model_name": os.getenv("LANGFLOW_MODEL", "llama-3.3-70b-versatile"),
            "api_key": os.getenv("GROQ_API_KEY", ""),
        }
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        return {
            "provider": "Google Generative AI",
            "model_name": os.getenv("LANGFLOW_MODEL", "gemini-2.0-flash"),
            "api_key": os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", ""),
        }
    if os.getenv("OPENAI_API_KEY"):
        return {
            "provider": "OpenAI",
            "model_name": os.getenv("LANGFLOW_MODEL", "gpt-4o-mini"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
        }
    return {"provider": "Groq", "model_name": "llama-3.3-70b-versatile", "api_key": ""}


# ── flow assembly ───────────────────────────────────────────────────────
def build_flow(agents: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    comps = fetch_components()
    if not comps:
        return None

    chat_in = pick(comps, ["ChatInput"])
    chat_out = pick(comps, ["ChatOutput"])
    model = pick(comps, [
        "LanguageModelComponent", "LanguageModel", "GroqModel",
        "GoogleGenerativeAIModel", "OpenAIModel", "ChatGroq", "ChatOpenAI",
    ])

    missing = [n for n, v in
               (("ChatInput", chat_in), ("ChatOutput", chat_out), ("a model", model))
               if v is None]
    if missing:
        print("  missing components on this Langflow build:", ", ".join(missing))
        return None

    in_kind, in_tmpl = chat_in
    md_kind, md_tmpl = model
    out_kind, out_tmpl = chat_out
    print(f"  using {in_kind} -> {md_kind} -> {out_kind}")

    n_in = make_node(in_kind, in_tmpl, new_id(in_kind), 120, 260)
    n_md = make_node(md_kind, md_tmpl, new_id(md_kind), 620, 200)
    n_out = make_node(out_kind, out_tmpl, new_id(out_kind), 1120, 260)

    cfg = model_settings()
    set_field(n_md, "system_message", build_planner_prompt(agents))
    for f in ("provider", "model_provider"):
        if set_field(n_md, f, cfg["provider"]):
            break
    for f in ("model_name", "model", "model_id"):
        if set_field(n_md, f, cfg["model_name"]):
            break
    for f in ("api_key", "groq_api_key", "openai_api_key", "google_api_key"):
        if cfg["api_key"] and set_field(n_md, f, cfg["api_key"]):
            break
    set_field(n_md, "temperature", 0.1)
    set_field(n_in, "input_value", "Should I buy 200 sq yards in Gurugram Sector 79?")

    edges = [
        make_edge(n_in, n_md, ["input_value", "input", "text"]),
        make_edge(n_md, n_out, ["input_value", "input", "text"]),
    ]

    return {
        "name": lf.get_flow_name(),
        "description": (
            "LandIQ orchestration planner. Receives a land investment query "
            f"plus the {len(agents)} agents currently registered in LandIQ, "
            "and returns the JSON execution plan (which agents run, in which "
            "parallel layers). LandIQ calls this flow through /langflow/plan."
        ),
        "data": {"nodes": [n_in, n_md, n_out], "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.8}},
        "is_component": False,
    }


def upsert_flow(flow: Dict[str, Any]) -> Optional[str]:
    listing = lf.list_flows()
    existing = None
    if listing["ok"]:
        for f in listing["flows"]:
            if (f["name"] or "").strip().lower() == flow["name"].strip().lower():
                existing = f["id"]
                break

    if existing:
        ok, data, err = lf._request(
            "PATCH", f"/api/v1/flows/{existing}", json_body=flow, timeout=60.0
        )
        if ok:
            print(f"  updated existing flow ({existing})")
            return existing
        print("  update failed:", err)

    ok, data, err = lf._request("POST", "/api/v1/flows/", json_body=flow, timeout=60.0)
    if ok and isinstance(data, dict) and data.get("id"):
        print(f"  created new flow ({data['id']})")
        return data["id"]
    print("  create failed:", err)
    return None


def main() -> int:
    print("\nLandIQ -> Langflow setup")
    print("=" * 52)

    h = lf.health(force=True)
    print(f"Langflow  : {h['base_url']}")
    if not h["online"]:
        print(f"  OFFLINE — {h['error']}")
        print("\n  Start Langflow in a separate terminal first:")
        print("    langflow run --host 127.0.0.1 --port 7860")
        print("  Then run this script again.")
        return 1
    print(f"  online (version {h['version']}, {h['latency_ms']} ms)")

    agents = discover_agents()
    print(f"\nAgents    : {len(agents)} found in agents_registry/")
    for a in agents:
        print(f"  - {a['name']}")
    if not agents:
        print("  WARNING: registry is empty. The flow will still be created,")
        print("  but re-run this script once your agents are in place.")

    print("\nBuilding flow ...")
    flow = build_flow(agents)

    out_file = ROOT / "landiq_flow.json"
    if flow:
        out_file.write_text(json.dumps(flow, indent=2), encoding="utf-8")
        print(f"  saved a copy to {out_file.name}")

        flow_id = upsert_flow(flow)
        if flow_id:
            lf.set_flow_id(flow_id, flow["name"])
            print("\nDone.")
            print(f"  flow name : {flow['name']}")
            print(f"  flow id   : {flow_id}")
            print(f"  open it   : {h['base_url']}/flow/{flow_id}")
            print("  verify    : python verify_langflow.py")
            return 0

    print("\nProgrammatic create did not go through.")
    if flow:
        print(f"  Import {out_file.name} manually instead:")
        print(f"    1. open {h['base_url']}")
        print("    2. New Flow -> Import -> pick landiq_flow.json")
        print("    3. run: python verify_langflow.py  (it auto-detects the flow)")
    else:
        print("  Build the flow by hand in the Langflow UI:")
        print("    Chat Input -> Language Model -> Chat Output")
        print(f"    name it exactly: {lf.get_flow_name()}")
        print("    paste this into the model's System Message field:\n")
        print(build_planner_prompt(agents))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
