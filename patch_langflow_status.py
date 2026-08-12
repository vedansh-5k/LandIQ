"""
patch_langflow_status.py
------------------------
Run this ONCE in your project root:
    python patch_langflow_status.py

It patches the /langflow/status endpoint in api.py to:
  1. Use correct Langflow health URL (/health not /health_check)
  2. Read flow ID from langflow_flow_id.txt first
  3. Fall back to searching by name if file not found
"""

import re

API_FILE = "api.py"

OLD_BLOCK = '''@app.get("/langflow/status")
async def get_langflow_status():
    """Check if Langflow is running and LandIQ flow exists."""
    try:
        import httpx
        r = httpx.get("http://localhost:7860/health_check", timeout=3)
        langflow_up = r.status_code == 200
    except Exception:
        langflow_up = False

    flow_id = None
    if langflow_up:
        try:
            import httpx
            r = httpx.get("http://localhost:7860/api/v1/auto_login", timeout=3)
            token = r.json().get("access_token", "")
            r2 = httpx.get(
                "http://localhost:7860/api/v1/flows/?get_all=true&header_flows=true",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5
            )
            for f in r2.json():
                if "landiq" in f.get("name", "").lower():
                    flow_id = f["id"]
                    break
        except Exception:
            pass

    return {
        "langflow_url":  "http://localhost:7860",
        "reachable":     langflow_up,
        "flow_id":       flow_id,
        "flow_ready":    flow_id is not None,
        "mode":          "langflow" if (langflow_up and flow_id) else "local_orchestrator",
    }'''

NEW_BLOCK = '''@app.get("/langflow/status")
async def get_langflow_status():
    """Check if Langflow is running and LandIQ flow exists."""
    LANGFLOW = "http://localhost:7860"
    langflow_up = False

    # 1. Health check — try both URLs
    for path in ["/health", "/health_check", "/api/v1/config"]:
        try:
            r = httpx.get(f"{LANGFLOW}{path}", timeout=3)
            if r.status_code == 200:
                langflow_up = True
                break
        except Exception:
            continue

    # 2. Find flow ID — file first, then API search
    flow_id = None
    flow_name = None
    has_nodes = False
    node_count = 0

    # 2a. Read from langflow_flow_id.txt
    flow_file = _Path("langflow_flow_id.txt")
    if flow_file.exists():
        flow_id = flow_file.read_text().strip()

    # 2b. If no file, search Langflow API
    if not flow_id and langflow_up:
        try:
            r = httpx.get(f"{LANGFLOW}/api/v1/auto_login", timeout=3)
            token = r.json().get("access_token", "")
            r2 = httpx.get(
                f"{LANGFLOW}/api/v1/flows/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            flows = r2.json()
            if isinstance(flows, list):
                for f in flows:
                    fname = f.get("name", "").lower()
                    if "landiq" in fname or "land" in fname:
                        flow_id = f["id"]
                        flow_name = f.get("name")
                        break
                # If no match by name, take the first flow
                if not flow_id and flows:
                    flow_id = flows[0]["id"]
                    flow_name = flows[0].get("name", "Unknown")
        except Exception:
            pass

    # 3. Check if flow has nodes (not empty)
    if flow_id and langflow_up:
        try:
            r = httpx.get(f"{LANGFLOW}/api/v1/flows/{flow_id}", timeout=5)
            if r.status_code == 200:
                fdata = r.json()
                flow_name = fdata.get("name", flow_name)
                nodes = fdata.get("data", {}).get("nodes", [])
                has_nodes = len(nodes) > 0
                node_count = len(nodes)
        except Exception:
            pass

    return {
        "langflow_url": LANGFLOW,
        "reachable": langflow_up,
        "flow_id": flow_id,
        "flow_name": flow_name,
        "has_nodes": has_nodes,
        "node_count": node_count,
        "flow_ready": flow_id is not None and has_nodes,
        "mode": "langflow" if (langflow_up and flow_id and has_nodes) else "local_orchestrator",
        "architecture": "dual-path: langflow-first, local-fallback",
    }'''


def main():
    with open(API_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    if OLD_BLOCK not in content:
        print("ERROR: Could not find the old /langflow/status block in api.py")
        print("Maybe it was already patched or modified.")
        print()
        print("Manual fix: replace the get_langflow_status function with the new version.")
        return

    new_content = content.replace(OLD_BLOCK, NEW_BLOCK)

    with open(API_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)

    print("=" * 50)
    print("  PATCHED api.py successfully!")
    print("=" * 50)
    print()
    print("  Fixed:")
    print("  1. Health check tries /health, /health_check, /api/v1/config")
    print("  2. Reads flow ID from langflow_flow_id.txt first")
    print("  3. Falls back to API search if no file")
    print("  4. Checks if flow has nodes (not empty)")
    print("  5. Returns node_count and has_nodes in response")
    print()
    print("  Next: python setup_langflow_v2.py")
    print()


if __name__ == "__main__":
    main()
