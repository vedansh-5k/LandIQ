"""
patch_api_langflow.py
Adds 3 Langflow endpoints to api.py — fully additive, no existing code touched.
Inserts ABOVE 'if __name__' so FastAPI registers the routes.
"""
import re
import sys
import shutil

API_FILE = "api.py"
BACKUP = "api.py.backup_before_langflow"

LANGFLOW_CODE = '''

# ═══════════════════════════════════════════════════════════════
# LANGFLOW VISUAL ORCHESTRATOR — additive integration
# Dual-path: Langflow first → local orchestrator fallback
# These endpoints let the frontend check Langflow status and
# optionally route queries through the visual pipeline.
# ═══════════════════════════════════════════════════════════════

try:
    from src.utils.langflow_bridge import (
        is_langflow_running, run_via_langflow, get_flow_id
    )
    _LANGFLOW_BRIDGE_OK = True
except ImportError:
    _LANGFLOW_BRIDGE_OK = False


@app.get("/langflow/status")
async def langflow_status():
    """Check if the Langflow visual orchestrator is running and connected."""
    if not _LANGFLOW_BRIDGE_OK:
        return {"running": False, "error": "langflow_bridge.py not found in src/utils/"}
    return is_langflow_running()


@app.post("/langflow/run")
async def langflow_run_endpoint(request: Request):
    """Run a query through the Langflow visual pipeline."""
    if not _LANGFLOW_BRIDGE_OK:
        raise HTTPException(status_code=503, detail="Langflow bridge not installed")
    body = await request.json()
    query = body.get("query", body.get("input_value", ""))
    if not query:
        raise HTTPException(status_code=400, detail="query field is required")
    result = run_via_langflow(query, tweaks=body.get("tweaks"))
    if not result.get("success"):
        raise HTTPException(status_code=503, detail=result.get("error", "Langflow failed"))
    return result


@app.get("/langflow/flow-id")
async def langflow_get_flow_id():
    """Return the active Langflow flow ID and UI link."""
    if not _LANGFLOW_BRIDGE_OK:
        return {"flow_id": None, "error": "bridge not installed"}
    fid = get_flow_id()
    return {
        "flow_id": fid or None,
        "ui_url": f"http://localhost:7860/flow/{fid}" if fid else None,
    }

'''


def patch():
    # ── Read current api.py ──
    try:
        with open(API_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"✗ {API_FILE} not found. Run from project root.")
        sys.exit(1)

    # ── Already patched? ──
    if "/langflow/status" in content:
        print("✓ api.py already has Langflow endpoints — nothing to do.")
        return

    # ── Backup ──
    shutil.copy2(API_FILE, BACKUP)
    print(f"✓ Backup saved: {BACKUP}")

    # ── Find insertion point: ABOVE 'if __name__ == "__main__":' ──
    pattern = r'\n(if\s+__name__\s*==\s*["\']__main__["\'])'
    match = re.search(pattern, content)

    if match:
        pos = match.start()
        new_content = content[:pos] + LANGFLOW_CODE + "\n" + content[pos:]
        line_num = content[:pos].count("\n") + 1
        print(f"✓ Inserting Langflow block at line ~{line_num} (above if __name__)")
    else:
        # No if __name__ block — append at end
        new_content = content + LANGFLOW_CODE
        print("✓ Appending Langflow block at end of file")

    # ── Write ──
    with open(API_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"✓ api.py patched! New endpoints:")
    print(f"  GET  /langflow/status   → is Langflow running?")
    print(f"  POST /langflow/run      → execute query via Langflow")
    print(f"  GET  /langflow/flow-id  → current flow ID + UI link")
    print(f"\n  To undo: copy {BACKUP} back to {API_FILE}")


if __name__ == "__main__":
    patch()
