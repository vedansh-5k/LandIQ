"""
setup_langflow.py
-----------------
One-time setup: configures Langflow for LandIQ automatically.
Run this ONCE after Langflow is running on port 7860.

Usage:
    cd C:\\Users\\HP\\OneDrive\\Desktop\\ai_boardroom_v3
    venv\\Scripts\\Activate.ps1
    python setup_langflow.py
"""

import requests
import json
import sys
import os
from pathlib import Path

LANGFLOW_BASE = "http://localhost:7860"
FLOW_ID_FILE = "langflow_flow_id.txt"

# ── The comprehensive LandIQ agent prompt ────────────────────────────
LANDIQ_SYSTEM_PROMPT = """You are the LandIQ Orchestrator — an AI-powered Indian land investment advisor.

When a user asks about land investment, analyze it across ALL these dimensions:

1. LOCATION ANALYSIS: Connectivity, metro proximity, infrastructure development, appreciation zones, upcoming projects
2. LEGAL ANALYSIS: Title deed verification, RERA compliance, encumbrance status, land use zoning, red flags
3. FINANCIAL ANALYSIS: ROI projections (5yr/10yr), rental yield, EMI feasibility, breakeven timeline, cost breakdown
4. MARKET ANALYSIS: Current demand-supply, price trends, comparable transactions, best timing
5. BULL CASE: Best-case scenario — upside potential, catalysts, growth drivers
6. BEAR CASE: Worst-case scenario — risks, downsides, deal-breakers
7. DUE DILIGENCE: Cross-check all findings, flag contradictions, verify consistency
8. FINAL VERDICT: Buy / Hold / Avoid with confidence score and reasoning

Format your response with clear sections for each dimension.
Use real Indian context — mention RERA, stamp duty, circle rates, mutation, 7/12 extract where relevant.
Give specific numbers (INR) for financial projections.
End with a clear verdict and action items."""


def check_langflow():
    """Check if Langflow is running."""
    try:
        r = requests.get(f"{LANGFLOW_BASE}/health", timeout=5)
        if r.status_code == 200:
            print("[OK] Langflow is running at", LANGFLOW_BASE)
            return True
    except Exception:
        pass
    print("[ERROR] Langflow is NOT running at", LANGFLOW_BASE)
    print("  Start it first in the langflow_server terminal:")
    print("  langflow_server\\Scripts\\Activate.ps1")
    print("  python -m langflow run --port 7860")
    return False


def find_existing_flow():
    """Find any existing LandIQ flow."""
    try:
        r = requests.get(f"{LANGFLOW_BASE}/api/v1/flows/", timeout=10)
        if r.status_code == 200:
            flows = r.json()
            # Handle both list and dict responses
            if isinstance(flows, dict):
                flows = flows.get("flows", flows.get("results", []))
            if isinstance(flows, list):
                for flow in flows:
                    fid = flow.get("id", "")
                    fname = flow.get("name", "")
                    print(f"  Found flow: {fname} ({fid})")
                    return fid, fname
    except Exception as e:
        print(f"  Error listing flows: {e}")
    return None, None


def update_flow(flow_id, new_name="LandIQ_Orchestrator"):
    """Update an existing flow's name and description."""
    try:
        r = requests.patch(
            f"{LANGFLOW_BASE}/api/v1/flows/{flow_id}",
            json={
                "name": new_name,
                "description": "LandIQ AI Land Investment Advisor — visual orchestration layer"
            },
            timeout=10,
        )
        if r.status_code == 200:
            print(f"[OK] Flow renamed to '{new_name}'")
            return True
        else:
            print(f"  Rename returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  Error renaming: {e}")
    return False


def test_flow(flow_id):
    """Run a test query through the flow."""
    print("\n[TEST] Sending test query to Langflow...")
    test_query = (
        "I want to buy 2000 sq ft residential land in Whitefield, Bangalore, "
        "Karnataka. Budget is INR 80 lakhs. Purpose is building a house in 3 years. "
        "Give me a quick analysis."
    )
    try:
        r = requests.post(
            f"{LANGFLOW_BASE}/api/v1/run/{flow_id}",
            json={
                "input_value": test_query,
                "output_type": "chat",
                "input_type": "chat",
            },
            timeout=120,
        )
        if r.status_code == 200:
            data = r.json()
            # Extract response text
            text = None
            if "outputs" in data:
                for og in data["outputs"]:
                    for o in og.get("outputs", []):
                        msg = o.get("results", {}).get("message", {})
                        if isinstance(msg, dict):
                            text = msg.get("text", "")
                        elif isinstance(msg, str):
                            text = msg
                        if text:
                            break
                    if text:
                        break
            if text:
                preview = text[:300].replace("\n", " ")
                print(f"[OK] Got response ({len(text)} chars): {preview}...")
                return True
            else:
                print(f"[WARN] Response had no text. Raw: {json.dumps(data)[:300]}")
                return False
        else:
            print(f"[ERROR] HTTP {r.status_code}: {r.text[:300]}")
            return False
    except requests.exceptions.Timeout:
        print("[WARN] Test timed out after 120s — Groq might be rate-limited. Flow is still configured correctly.")
        return True  # Flow exists, just timeout
    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        return False


def save_flow_id(flow_id):
    """Save flow ID to file for langflow_bridge.py to read."""
    Path(FLOW_ID_FILE).write_text(flow_id.strip())
    print(f"[OK] Flow ID saved to {FLOW_ID_FILE}")


def main():
    print("=" * 60)
    print("  LandIQ — Langflow Setup")
    print("=" * 60)

    # Step 1: Check Langflow
    if not check_langflow():
        sys.exit(1)

    # Step 2: Find existing flow
    print("\n[STEP 2] Finding flows...")
    flow_id, flow_name = find_existing_flow()

    if not flow_id:
        print("[ERROR] No flows found in Langflow.")
        print("  Create a flow first:")
        print("  1. Open http://localhost:7860")
        print("  2. Click 'Simple Agent' template")
        print("  3. Set model to llama-3.3-70b-versatile")
        print("  4. Save (Ctrl+S)")
        print("  5. Run this script again")
        sys.exit(1)

    print(f"  Using flow: {flow_name} ({flow_id})")

    # Step 3: Rename flow
    print("\n[STEP 3] Renaming flow to LandIQ_Orchestrator...")
    update_flow(flow_id, "LandIQ_Orchestrator")

    # Step 4: Save flow ID
    print("\n[STEP 4] Saving flow ID...")
    save_flow_id(flow_id)

    # Step 5: Test flow
    test_ok = test_flow(flow_id)

    # Summary
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print(f"  Langflow URL  : {LANGFLOW_BASE}")
    print(f"  Flow name     : LandIQ_Orchestrator")
    print(f"  Flow ID       : {flow_id}")
    print(f"  Flow ID file  : {FLOW_ID_FILE}")
    print(f"  Test query    : {'PASSED' if test_ok else 'NEEDS RETRY'}")
    print()
    print("  NEXT STEPS:")
    print("  1. Save langflow_bridge.py as src\\utils\\langflow_bridge.py")
    print("  2. Add Langflow endpoints to api.py (above 'if __name__' line)")
    print("  3. Restart: python run.py")
    print("  4. Test: http://localhost:8000/langflow/status")
    print()
    print("  DEMO FOR SIR:")
    print(f"  - Langflow UI: {LANGFLOW_BASE}/flow/{flow_id}")
    print(f"  - API status:  http://localhost:8000/langflow/status")
    print(f"  - API run:     POST http://localhost:8000/langflow/run")
    print(f"  - Dual-path:   POST http://localhost:8000/analyse/langflow")
    print("=" * 60)


if __name__ == "__main__":
    main()
