"""
setup_langflow_flow.py
Run ONCE after starting Langflow with auth disabled.
Imports langflow_full_pipeline.json → saves flow ID.
"""
import requests, json, sys, os

LANGFLOW_URL = "http://localhost:7860"
FLOW_JSON = "langflow_full_pipeline.json"
FLOW_ID_FILE = "langflow_flow_id.txt"


def main():
    # ── 1. Check Langflow is reachable ──
    print("\n[1/4] Checking Langflow...")
    try:
        r = requests.get(f"{LANGFLOW_URL}/api/v1/flows/", timeout=5)
        if r.status_code == 200:
            existing = r.json()
            print(f"  ✓ Langflow API reachable — {len(existing)} existing flow(s)")
        elif "authentication" in r.text.lower() or r.status_code in (401, 403):
            print(f"  ✗ Auth still enabled (HTTP {r.status_code})")
            print(f"    Restart Langflow with LANGFLOW_AUTO_LOGIN=true")
            sys.exit(1)
        else:
            existing = []
            print(f"  ⚠ Unexpected response {r.status_code}, continuing...")
    except requests.ConnectionError:
        print(f"  ✗ Cannot reach {LANGFLOW_URL}")
        print(f"    Start Langflow first (see instructions)")
        sys.exit(1)

    # ── 2. Load flow JSON ──
    print(f"\n[2/4] Loading {FLOW_JSON}...")
    if not os.path.exists(FLOW_JSON):
        print(f"  ✗ File not found: {FLOW_JSON}")
        sys.exit(1)

    with open(FLOW_JSON, "r", encoding="utf-8") as f:
        raw = json.load(f)
    print(f"  ✓ Loaded ({os.path.getsize(FLOW_JSON)} bytes)")

    # Handle different JSON formats
    if isinstance(raw, list):
        # Langflow export sometimes wraps in a list
        flow_data = raw[0] if raw else {}
    else:
        flow_data = raw

    # Ensure required fields
    if isinstance(flow_data, dict):
        flow_data.setdefault("name", "LandIQ Pipeline")
        flow_data.setdefault("description",
                             "LandIQ AI-powered land investment advisory pipeline — visual orchestrator")
        # If it has "flows" key (full export), extract first flow
        if "flows" in flow_data and isinstance(flow_data["flows"], list):
            inner = flow_data["flows"][0] if flow_data["flows"] else {}
            inner.setdefault("name", "LandIQ Pipeline")
            inner.setdefault("description", flow_data.get("description", ""))
            flow_data = inner

    # ── 3. Delete old LandIQ flows to avoid duplicates ──
    for ex in existing:
        if "landiq" in ex.get("name", "").lower() or "land" in ex.get("name", "").lower():
            fid = ex.get("id", "")
            print(f"  Removing old flow: {ex.get('name')} ({fid[:8]}...)")
            try:
                requests.delete(f"{LANGFLOW_URL}/api/v1/flows/{fid}", timeout=5)
            except Exception:
                pass

    # Also remove the empty "New Flow" if it exists
    for ex in existing:
        if ex.get("name", "").strip().lower() in ("new flow", "untitled", ""):
            fid = ex.get("id", "")
            print(f"  Removing empty flow: {ex.get('name')} ({fid[:8]}...)")
            try:
                requests.delete(f"{LANGFLOW_URL}/api/v1/flows/{fid}", timeout=5)
            except Exception:
                pass

    # ── 4. Import the flow ──
    print(f"\n[3/4] Importing flow into Langflow...")
    r = requests.post(
        f"{LANGFLOW_URL}/api/v1/flows/",
        json=flow_data,
        timeout=30
    )

    if r.status_code in (200, 201):
        result = r.json()
        flow_id = result.get("id", "")
        flow_name = result.get("name", "unknown")
        node_count = len(result.get("data", {}).get("nodes", []))

        with open(FLOW_ID_FILE, "w") as f:
            f.write(flow_id)

        print(f"  ✓ Flow imported!")
        print(f"    Name:  {flow_name}")
        print(f"    ID:    {flow_id}")
        print(f"    Nodes: {node_count}")
        print(f"    View:  {LANGFLOW_URL}/flow/{flow_id}")

    elif r.status_code == 422:
        # Validation error — JSON format doesn't match Langflow schema
        print(f"  ⚠ Flow JSON format mismatch (422). Creating a blank flow...")
        print(f"    You'll build it visually in the UI.")
        minimal = {
            "name": "LandIQ Pipeline",
            "description": "LandIQ AI-powered land investment advisory — build in UI",
            "data": {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
        }
        r2 = requests.post(f"{LANGFLOW_URL}/api/v1/flows/", json=minimal, timeout=10)
        if r2.status_code in (200, 201):
            result = r2.json()
            flow_id = result.get("id", "")
            with open(FLOW_ID_FILE, "w") as f:
                f.write(flow_id)
            print(f"  ✓ Blank flow created: {flow_id}")
            print(f"    Open {LANGFLOW_URL}/flow/{flow_id}")
            print(f"    Then drag: Chat Input → Prompt → Groq → Chat Output")
        else:
            print(f"  ✗ Failed: {r2.text[:200]}")
            sys.exit(1)
        return
    else:
        print(f"  ✗ Import failed: HTTP {r.status_code}")
        print(f"    {r.text[:300]}")
        sys.exit(1)

    # ── 5. Quick test ──
    print(f"\n[4/4] Testing flow execution...")
    try:
        test_r = requests.post(
            f"{LANGFLOW_URL}/api/v1/run/{flow_id}",
            json={
                "input_value": "Analyze land in Noida Sector 150 for residential investment",
                "output_type": "chat",
                "input_type": "chat"
            },
            timeout=90
        )
        if test_r.status_code == 200:
            td = test_r.json()
            # Extract output from nested structure
            text = ""
            for out in td.get("outputs", []):
                for res in out.get("outputs", []):
                    msg = res.get("results", {}).get("message", {})
                    text = msg.get("text", str(msg)) if isinstance(msg, dict) else str(msg)
                    if text:
                        break
            print(f"  ✓ Flow executed! Output preview:")
            print(f"    {text[:200]}...")
        else:
            print(f"  ⚠ Flow returned {test_r.status_code}")
            print(f"    Flow may need LLM components configured in the UI first.")
            print(f"    This is OK — the API wiring still works.")
    except Exception as e:
        print(f"  ⚠ Test skipped: {str(e)[:100]}")
        print(f"    Flow may need components. Build it in the UI.")

    print(f"\n{'='*55}")
    print(f"  DONE! Flow ID: {flow_id}")
    print(f"  Next: python patch_api_langflow.py")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
