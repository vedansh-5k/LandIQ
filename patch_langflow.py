"""
patch_langflow.py — Adds Langflow routes to api.py
Run from project root:  python patch_langflow.py
"""
import re

API_FILE = "api.py"
FLOW_ID = "19145c80-276e-4331-88d8-6e19403bf689"

# ── Save flow ID ─────────────────────────────────────
with open("langflow_flow_id.txt", "w") as f:
    f.write(FLOW_ID)
print(f"[1/3] Saved flow ID to langflow_flow_id.txt")

# ── Read api.py ──────────────────────────────────────
with open(API_FILE, "r", encoding="utf-8") as f:
    code = f.read()

# ── Check if already patched ─────────────────────────
if "/langflow/status" in code:
    print("[!] Langflow routes already in api.py — skipping patch")
    exit(0)

# ── The code block to insert ─────────────────────────
LANGFLOW_BLOCK = '''

# ══════════════════════════════════════════════════════
#  LANGFLOW INTEGRATION — added by patch_langflow.py
# ══════════════════════════════════════════════════════
from src.utils.langflow_bridge import langflow_status, run_via_langflow

@app.get("/langflow/status")
def get_langflow_status():
    """Check if Langflow is reachable and flow is configured."""
    return langflow_status()

@app.post("/langflow/run")
def run_langflow_pipeline(req: LandQueryRequest):
    """Run analysis through Langflow visual pipeline."""
    try:
        result = run_via_langflow(req.model_dump())
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e), "fallback": "use /analyse instead"}

@app.get("/langflow/flow-id")
def get_langflow_flow_id():
    """Return the configured Langflow flow ID."""
    from src.utils.langflow_bridge import _get_flow_id
    fid = _get_flow_id()
    return {"flow_id": fid or "not_configured"}

# ══════════════════════════════════════════════════════

'''

# ── Insert ABOVE 'if __name__' ───────────────────────
pattern = r'(\nif __name__\s*==\s*["\']__main__["\'])'
match = re.search(pattern, code)

if not match:
    print("[ERROR] Could not find 'if __name__' in api.py")
    exit(1)

pos = match.start()
new_code = code[:pos] + LANGFLOW_BLOCK + code[pos:]

# ── Write back ───────────────────────────────────────
with open(API_FILE, "w", encoding="utf-8") as f:
    f.write(new_code)

print(f"[2/3] Inserted 3 Langflow routes into api.py (before line {code[:pos].count(chr(10))+1})")
print(f"[3/3] Done! Restart with: python run.py")
print(f"")
print(f"Test these URLs:")
print(f"  http://localhost:8000/langflow/status")
print(f"  http://localhost:8000/langflow/flow-id")
print(f"  POST http://localhost:8000/langflow/run")
