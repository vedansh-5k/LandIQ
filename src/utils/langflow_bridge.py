"""
langflow_bridge.py
------------------
Connects LandIQ to Langflow (visual LLM workflow builder).
Dual-path: tries Langflow first, falls back to local orchestrator.

Runtime config (base_url / api_key / flow_id / flow_name) is stored in
LANGFLOW_STATE_FILE and can be changed live via /langflow/set-url and
/langflow/set-flow - nothing here is hardcoded. Falls back to env vars and
the langflow_flow_id.txt / langflow_api_key.txt files dropped by
setup_langflow.py when no runtime override has been set yet.

Provides BOTH naming conventions so any api.py import works:
  - check_langflow_status / run_langflow          (async)
  - is_langflow_running / run_via_langflow / get_flow_id
  - status / health / list_flows / flow_graph / plan_execution / run_flow
    (used by src/utils/langflow_routes.py)
"""

import json
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_FILE = ROOT / "langflow_state.json"

_DEFAULT_BASE = os.environ.get("LANGFLOW_BASE_URL", "http://127.0.0.1:7860")

# Cache health checks briefly so status-polling UIs don't hammer Langflow.
_HEALTH_CACHE = {"ts": 0.0, "data": None}
_HEALTH_TTL = 5.0


# ── runtime state (dynamic, no hardcoding) ─────────────────────────────────
def _read_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_state(patch):
    state = _read_state()
    state.update(patch)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def get_base_url():
    return _read_state().get("base_url") or _DEFAULT_BASE


def set_base_url(url):
    _write_state({"base_url": url.rstrip("/")})


def get_api_key():
    state_key = _read_state().get("api_key")
    if state_key:
        return state_key
    env_key = os.environ.get("LANGFLOW_API_KEY", "")
    if env_key:
        return env_key
    p = ROOT / "langflow_api_key.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def set_api_key(key):
    _write_state({"api_key": key})


def get_flow_name():
    return _read_state().get("flow_name")


def get_flow_id():
    """Read flow ID: runtime override -> langflow_flow_id.txt -> env var."""
    override = _read_state().get("flow_id")
    if override:
        return override
    for p in [ROOT / "langflow_flow_id.txt", Path("langflow_flow_id.txt")]:
        if p.exists():
            fid = p.read_text(encoding="utf-8").strip()
            if fid:
                return fid
    return os.environ.get("LANGFLOW_FLOW_ID", "") or None


def _stored_flow_id():
    return get_flow_id()


def set_flow_id(flow_id, flow_name=None):
    patch = {"flow_id": flow_id}
    if flow_name is not None:
        patch["flow_name"] = flow_name
    _write_state(patch)


# Keep old private name working too
_get_flow_id = get_flow_id


def _headers():
    key = get_api_key()
    return {"x-api-key": key} if key else {}


# ── health / status ─────────────────────────────────────────────────────
def is_langflow_running():
    """Synchronous check - returns True if Langflow health endpoint responds."""
    try:
        r = httpx.get(f"{get_base_url()}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


async def check_langflow_status():
    """Async status check. Returns a dict with server/reachable/flow info."""
    base = get_base_url()
    flow_id = get_flow_id()
    status = {
        "server": base,
        "reachable": False,
        "flow_id": flow_id,
        "flow_configured": flow_id is not None,
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base}/health")
            status["reachable"] = resp.status_code == 200
    except Exception:
        pass
    return status


def health(use_cache=True):
    """Synchronous, cached health check used by /langflow/health."""
    now = time.time()
    if use_cache and _HEALTH_CACHE["data"] is not None and (now - _HEALTH_CACHE["ts"]) < _HEALTH_TTL:
        return _HEALTH_CACHE["data"]
    base = get_base_url()
    try:
        r = httpx.get(f"{base}/health", timeout=5)
        data = {"reachable": r.status_code == 200, "base_url": base, "status_code": r.status_code}
    except Exception as e:
        data = {"reachable": False, "base_url": base, "error": str(e)[:200]}
    _HEALTH_CACHE["ts"] = now
    _HEALTH_CACHE["data"] = data
    return data


def status():
    """Synchronous, richer status used by /langflow/status (via the router)."""
    h = health()
    fid = get_flow_id()
    return {
        "online": h.get("reachable", False),
        "base_url": get_base_url(),
        "flow_id": fid,
        "flow_name": get_flow_name(),
        "flow_configured": fid is not None,
        "mode": "langflow" if (h.get("reachable") and fid) else "local_orchestrator",
    }


# ── flow introspection ──────────────────────────────────────────────────
def list_flows():
    base = get_base_url()
    try:
        r = httpx.get(f"{base}/api/v1/flows/", headers=_headers(), timeout=10)
        data = r.json() if r.status_code < 400 else []
        if isinstance(data, dict):
            data = data.get("items") or data.get("flows") or []
        return {
            "success": True,
            "count": len(data),
            "flows": [{"id": f.get("id"), "name": f.get("name")} for f in data],
        }
    except Exception as e:
        return {"success": False, "count": 0, "flows": [], "error": str(e)[:200]}


def flow_graph(flow_id=None):
    base = get_base_url()
    fid = flow_id or get_flow_id()
    if not fid:
        return {"success": False, "error": "no flow_id configured"}
    try:
        r = httpx.get(f"{base}/api/v1/flows/{fid}", headers=_headers(), timeout=15)
        if r.status_code >= 400:
            return {"success": False, "error": "HTTP %d: %s" % (r.status_code, r.text[:200])}
        data = r.json()
        nodes = data.get("data", {}).get("nodes", [])
        edges = data.get("data", {}).get("edges", [])
        return {
            "success": True,
            "id": fid,
            "name": data.get("name"),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": [
                {"id": n.get("id"), "type": n.get("data", {}).get("type")}
                for n in nodes
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── run ──────────────────────────────────────────────────────────────────
def _extract_text(data):
    """Pull the response text out of Langflow's nested output structure."""
    text = None
    if isinstance(data, dict) and "outputs" in data:
        for output_group in data["outputs"]:
            for output in output_group.get("outputs", []):
                results = output.get("results", {})
                message = results.get("message", {})
                if isinstance(message, dict):
                    text = message.get("text")
                elif isinstance(message, str):
                    text = message
                if text:
                    break
            if text:
                break
    return text


async def run_langflow(query, tweaks=None, timeout=600):
    """Async - send a query to Langflow. Returns dict or None (triggers fallback).

    timeout defaults to 600s as a safety margin: the flow runs up to 10
    agents via /run-single-agent, and even with a working primary model
    (no failed-then-fallback double call) that's still real LLM latency
    stacked across every agent. 600s gives real headroom without letting a
    genuinely hung run block forever.
    """
    base = get_base_url()
    flow_id = get_flow_id()
    if not flow_id:
        print("  [LANGFLOW] No flow_id configured — nothing to run")
        return None

    payload = {"input_value": query, "output_type": "chat", "input_type": "chat"}
    if tweaks:
        payload["tweaks"] = tweaks

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/api/v1/run/{flow_id}", json=payload, headers=_headers()
            )
            if resp.status_code != 200:
                print(f"  [LANGFLOW] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            langflow_result = resp.json()
            print(f"[LANGFLOW DEBUG] Response type: {type(langflow_result)}")
            print(f"[LANGFLOW DEBUG] Response content (first 1000 chars): {str(langflow_result)[:1000]}")
            if isinstance(langflow_result, dict):
                print(f"[LANGFLOW DEBUG] Response keys: {list(langflow_result.keys())}")
            text = _extract_text(langflow_result)
            # This is the condition the bridge itself uses to decide the run
            # produced something usable: _extract_text() must find a non-empty
            # outputs[].outputs[].results.message.text (or a plain string
            # message) in the raw Langflow response above. If that print
            # showed a populated "outputs" list but this still says "no text
            # extracted", the mismatch is inside _extract_text()'s nesting
            # assumptions, not the HTTP layer.
            print(f"[LANGFLOW DEBUG] _extract_text() found: "
                  f"{'yes, ' + str(len(text)) + ' chars' if text else 'NOTHING — this is what triggers the caller fallback'}")
            if text:
                return {"source": "langflow", "flow_id": flow_id, "response": text}
            return None
    except httpx.TimeoutException:
        print(f"  [LANGFLOW] Timeout after {timeout}s")
        return None
    except Exception as e:
        print(f"  [LANGFLOW] Error: {e}")
        return None


def run_via_langflow(query, tweaks=None):
    """Synchronous version - used by api.py code paths that aren't async."""
    base = get_base_url()
    flow_id = get_flow_id()
    if not flow_id:
        return None

    payload = {"input_value": query, "output_type": "chat", "input_type": "chat"}
    if tweaks:
        payload["tweaks"] = tweaks

    try:
        r = httpx.post(f"{base}/api/v1/run/{flow_id}", json=payload, headers=_headers(), timeout=300)
        if r.status_code != 200:
            print(f"  [LANGFLOW] HTTP {r.status_code}: {r.text[:200]}")
            return None
        text = _extract_text(r.json())
        if text:
            return {"source": "langflow", "flow_id": flow_id, "response": text}
        return None
    except httpx.TimeoutException:
        print("  [LANGFLOW] Timeout")
        return None
    except Exception as e:
        print(f"  [LANGFLOW] Error: {e}")
        return None


def run_flow(input_value, flow_id=None, tweaks=None, timeout=120.0):
    """Used by /langflow/run (router version) - same as run_via_langflow but
    with an explicit flow_id override and timeout, for programmatic callers."""
    base = get_base_url()
    fid = flow_id or get_flow_id()
    if not fid:
        return {"ok": False, "error": "no flow_id configured"}

    payload = {"input_value": input_value, "output_type": "chat", "input_type": "chat"}
    if tweaks:
        payload["tweaks"] = tweaks

    try:
        r = httpx.post(f"{base}/api/v1/run/{fid}", json=payload, headers=_headers(), timeout=timeout)
        if r.status_code != 200:
            return {"ok": False, "error": "HTTP %d: %s" % (r.status_code, r.text[:300])}
        data = r.json()
        text = _extract_text(data)
        return {"ok": True, "flow_id": fid, "response": text, "raw": data}
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout after %ss" % timeout}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ── planning ────────────────────────────────────────────────────────────
def plan_execution(query, agents):
    """
    Real LLM-driven execution plan (same planner LangIQ's local orchestrator
    uses), exposed here so a Langflow-side component can ask "what should run
    for this query" before deciding what to do next.

    ok=False is not a failure for LandIQ - the caller (langflow_routes.py)
    falls back to the local orchestrator's own planner, which always runs a
    full plan_execution() internally regardless of this endpoint anyway.
    """
    try:
        from src.graph.orchestrator_agent import plan_execution as _real_plan_execution
    except Exception as e:
        return {"ok": False, "error": "planner unavailable: %s" % str(e)[:150]}

    user_inputs = {
        "purpose": query,
        "area": "", "city": "", "state": "",
        "land_size": 0, "land_unit": "", "total_budget": 0,
        "selected_agents": agents or ["all"],
    }
    try:
        plan = _real_plan_execution(user_inputs)
        return {"ok": True, "plan": plan}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── compatibility stub ─────────────────────────────────────────────────
def clear_model_cache(agent_name=None):
    pass
