"""
fix_all_langflow.py — Fixes langflow_bridge.py + verifies api.py
Run from project root: python fix_all_langflow.py
"""
import os

# ── Step 1: Write correct langflow_bridge.py ─────────────
bridge_code = '''"""
langflow_bridge.py — LandIQ Langflow Bridge
"""
import os, json, time, logging, httpx

logger = logging.getLogger(__name__)

LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://localhost:7860")
_FLOW_ID = None
_TIMEOUT = 180


def _headers():
    try:
        r = httpx.get(f"{LANGFLOW_URL}/api/v1/auto_login", timeout=5)
        token = r.json().get("access_token", "")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    except Exception:
        return {"Content-Type": "application/json"}


def _find_flow_id():
    global _FLOW_ID
    if _FLOW_ID:
        return _FLOW_ID
    try:
        h = _headers()
        r = httpx.get(f"{LANGFLOW_URL}/api/v1/flows/?get_all=true&header_flows=true", headers=h, timeout=8)
        for f in r.json():
            if "landiq" in f.get("name", "").lower():
                _FLOW_ID = f["id"]
                return _FLOW_ID
    except Exception as e:
        logger.warning(f"Langflow flow lookup failed: {e}")
    return None


def is_langflow_available():
    try:
        r = httpx.get(f"{LANGFLOW_URL}/health_check", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def langflow_status():
    up = is_langflow_available()
    fid = _find_flow_id() if up else None
    return {
        "langflow_url": LANGFLOW_URL,
        "reachable": up,
        "flow_id": fid,
        "flow_ready": fid is not None,
        "mode": "langflow" if (up and fid) else "local_orchestrator",
    }


def run_via_langflow(user_inputs):
    fid = _find_flow_id()
    if not fid:
        return None

    h = _headers()
    payload = {
        "input_value": json.dumps({
            "location": user_inputs.get("area", ""),
            "city": user_inputs.get("city", ""),
            "state": user_inputs.get("state", ""),
            "budget": str(user_inputs.get("total_budget", "")),
            "purpose": user_inputs.get("purpose", ""),
            "land_type": user_inputs.get("land_type", ""),
        }),
        "output_type": "text",
        "input_type": "text",
        "tweaks": {},
    }

    try:
        t0 = time.time()
        r = httpx.post(f"{LANGFLOW_URL}/api/v1/run/{fid}", json=payload, headers=h, timeout=_TIMEOUT)
        if r.status_code != 200:
            logger.warning(f"Langflow returned {r.status_code}: {r.text[:200]}")
            return None

        data = r.json()
        duration = time.time() - t0
        state = {}

        outputs = data.get("outputs", [])
        for output_block in outputs:
            results = output_block.get("outputs", [])
            for result in results:
                inner = result.get("results", {})
                if isinstance(inner, dict):
                    text = inner.get("text", {})
                    if isinstance(text, str):
                        try:
                            parsed = json.loads(text)
                            state.update(parsed)
                        except json.JSONDecodeError:
                            state["langflow_raw"] = text
                    elif isinstance(text, dict):
                        state.update(text)

        state["orchestrator_source"] = "langflow"
        state["langflow_duration"] = round(duration, 1)
        return state

    except Exception as e:
        logger.warning(f"Langflow execution failed: {e}")
        return None
'''

path = os.path.join("src", "utils", "langflow_bridge.py")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    f.write(bridge_code)
print(f"[1/3] Wrote {path}")

# ── Step 2: Fix api.py langflow/run None crash ──────────
api = open("api.py", "r", encoding="utf-8").read()

old_return = 'return {"success": True, **result}'
new_return = '''if result is None:
            return {"success": False, "error": "Langflow flow returned no output", "note": "Visual canvas available at localhost:7860"}
        return {"success": True, **result}'''

if old_return in api:
    api = api.replace(old_return, new_return, 1)
    open("api.py", "w", encoding="utf-8").write(api)
    print("[2/3] Patched api.py langflow/run None handling")
else:
    print("[2/3] api.py already patched or different format — skipped")

# ── Step 3: Verify imports work ──────────────────────────
try:
    from src.utils.langflow_bridge import langflow_status, run_via_langflow
    print("[3/3] Import OK — langflow_status + run_via_langflow both found")
    print("\nDone! Run: python run.py")
except ImportError as e:
    print(f"[3/3] Import FAILED: {e}")
