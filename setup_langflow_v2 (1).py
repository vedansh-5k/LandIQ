"""
setup_langflow_v2.py
--------------------
Creates a REAL LandIQ flow in Langflow with actual components:
  ChatInput → Prompt → GroqModel → ChatOutput

Run ONCE after starting Langflow:
  python setup_langflow_v2.py

Saves flow ID to langflow_flow_id.txt
"""

import requests
import json
import os
import sys

LANGFLOW_URL = os.environ.get("LANGFLOW_URL", "http://localhost:7860")

# ── Flow definition with real nodes ──────────────────────────────
# This creates: ChatInput → Prompt → GroqModel → ChatOutput

FLOW_DATA = {
    "name": "LandIQ Advisor Flow",
    "description": "LandIQ multi-agent land investment advisor — Langflow orchestration layer",
    "data": {
        "nodes": [
            {
                "id": "ChatInput-landiq",
                "type": "genericNode",
                "position": {"x": 100, "y": 300},
                "data": {
                    "type": "ChatInput",
                    "node": {
                        "display_name": "Chat Input",
                        "description": "User query input",
                        "template": {
                            "input_value": {
                                "type": "str",
                                "value": "",
                                "display_name": "Text",
                                "required": False,
                                "is_list": False,
                            },
                            "should_store_message": {
                                "type": "bool",
                                "value": True,
                                "display_name": "Store Messages",
                            },
                            "sender": {
                                "type": "str",
                                "value": "User",
                                "display_name": "Sender Type",
                            },
                            "sender_name": {
                                "type": "str",
                                "value": "User",
                                "display_name": "Sender Name",
                            },
                        },
                        "base_classes": ["Message"],
                        "output_types": ["Message"],
                    },
                },
            },
            {
                "id": "Prompt-landiq",
                "type": "genericNode",
                "position": {"x": 450, "y": 200},
                "data": {
                    "type": "Prompt",
                    "node": {
                        "display_name": "LandIQ System Prompt",
                        "description": "System prompt for land investment analysis",
                        "template": {
                            "template": {
                                "type": "str",
                                "value": (
                                    "You are LandIQ, an AI-powered Indian land investment advisor.\n"
                                    "Analyse the user's query about land investment in India.\n"
                                    "Consider: location value, legal risks, financial ROI, market trends.\n"
                                    "Give a professional, data-driven assessment.\n\n"
                                    "User Query: {user_query}"
                                ),
                                "display_name": "Template",
                                "multiline": True,
                            },
                            "user_query": {
                                "type": "str",
                                "value": "",
                                "display_name": "user_query",
                                "input_types": ["Message", "Text"],
                            },
                        },
                        "base_classes": ["Message"],
                        "output_types": ["Message"],
                    },
                },
            },
            {
                "id": "GroqModel-landiq",
                "type": "genericNode",
                "position": {"x": 800, "y": 300},
                "data": {
                    "type": "GroqModel",
                    "node": {
                        "display_name": "Groq LLM",
                        "description": "Groq Llama 3.3 70B for fast inference",
                        "template": {
                            "groq_api_key": {
                                "type": "str",
                                "value": "",
                                "display_name": "Groq API Key",
                                "password": True,
                                "input_types": ["Message"],
                            },
                            "model_name": {
                                "type": "str",
                                "value": "llama-3.3-70b-versatile",
                                "display_name": "Model Name",
                            },
                            "temperature": {
                                "type": "float",
                                "value": 0.3,
                                "display_name": "Temperature",
                            },
                            "max_tokens": {
                                "type": "int",
                                "value": 2048,
                                "display_name": "Max Output Tokens",
                            },
                            "input_value": {
                                "type": "str",
                                "value": "",
                                "display_name": "Input",
                                "input_types": ["Message"],
                            },
                            "system_message": {
                                "type": "str",
                                "value": "",
                                "display_name": "System Message",
                                "input_types": ["Message"],
                            },
                        },
                        "base_classes": ["Message"],
                        "output_types": ["Message"],
                    },
                },
            },
            {
                "id": "ChatOutput-landiq",
                "type": "genericNode",
                "position": {"x": 1150, "y": 300},
                "data": {
                    "type": "ChatOutput",
                    "node": {
                        "display_name": "Chat Output",
                        "description": "Display the LLM response",
                        "template": {
                            "input_value": {
                                "type": "str",
                                "value": "",
                                "display_name": "Text",
                                "input_types": ["Message"],
                            },
                            "should_store_message": {
                                "type": "bool",
                                "value": True,
                                "display_name": "Store Messages",
                            },
                            "sender": {
                                "type": "str",
                                "value": "Machine",
                                "display_name": "Sender Type",
                            },
                            "sender_name": {
                                "type": "str",
                                "value": "LandIQ",
                                "display_name": "Sender Name",
                            },
                        },
                        "base_classes": ["Message"],
                        "output_types": ["Message"],
                    },
                },
            },
        ],
        "edges": [
            {
                "source": "ChatInput-landiq",
                "target": "Prompt-landiq",
                "sourceHandle": "ChatInput-landiq|Message",
                "targetHandle": "Prompt-landiq|user_query",
                "id": "edge-1",
            },
            {
                "source": "Prompt-landiq",
                "target": "GroqModel-landiq",
                "sourceHandle": "Prompt-landiq|Message",
                "targetHandle": "GroqModel-landiq|input_value",
                "id": "edge-2",
            },
            {
                "source": "GroqModel-landiq",
                "target": "ChatOutput-landiq",
                "sourceHandle": "GroqModel-landiq|Message",
                "targetHandle": "ChatOutput-landiq|input_value",
                "id": "edge-3",
            },
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
    },
}


def main():
    print("=" * 55)
    print("  LandIQ — Langflow Setup v2")
    print("=" * 55)

    # 1. Check Langflow is running
    print(f"\n[1/4] Checking Langflow at {LANGFLOW_URL}...")
    try:
        r = requests.get(f"{LANGFLOW_URL}/health", timeout=5)
        if r.status_code == 200:
            print("  ✓ Langflow is running")
        else:
            print(f"  ✗ Langflow returned {r.status_code}")
            sys.exit(1)
    except requests.ConnectionError:
        print("  ✗ Cannot reach Langflow. Start it first:")
        print("    Open a NEW terminal → activate langflow_server env → python -m langflow run")
        sys.exit(1)

    # 2. Delete old empty flow if exists
    print("\n[2/4] Checking for old empty flow...")
    old_flow_id = None
    if os.path.exists("langflow_flow_id.txt"):
        with open("langflow_flow_id.txt") as f:
            old_flow_id = f.read().strip()
        print(f"  Found old flow ID: {old_flow_id}")
        try:
            r = requests.delete(
                f"{LANGFLOW_URL}/api/v1/flows/{old_flow_id}",
                headers={"accept": "application/json"},
                timeout=10,
            )
            if r.status_code in (200, 204):
                print("  ✓ Deleted old empty flow")
            else:
                print(f"  ⚠ Could not delete old flow ({r.status_code}) — continuing anyway")
        except Exception as e:
            print(f"  ⚠ Delete failed: {e} — continuing anyway")
    else:
        print("  No old flow file found — creating fresh")

    # 3. Create new flow with real nodes
    print("\n[3/4] Creating LandIQ flow with components...")
    try:
        r = requests.post(
            f"{LANGFLOW_URL}/api/v1/flows/",
            headers={"accept": "application/json", "Content-Type": "application/json"},
            json=FLOW_DATA,
            timeout=15,
        )
        if r.status_code in (200, 201):
            flow = r.json()
            flow_id = flow.get("id", "")
            print(f"  ✓ Flow created: {flow_id}")
            print(f"  ✓ Name: {flow.get('name', 'LandIQ Advisor Flow')}")
        else:
            print(f"  ✗ Failed ({r.status_code}): {r.text[:200]}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Error: {e}")
        sys.exit(1)

    # 4. Save flow ID
    print("\n[4/4] Saving flow ID...")
    with open("langflow_flow_id.txt", "w") as f:
        f.write(flow_id)
    print(f"  ✓ Saved to langflow_flow_id.txt")

    print("\n" + "=" * 55)
    print("  ✓ SETUP COMPLETE")
    print("=" * 55)
    print(f"\n  Flow URL: {LANGFLOW_URL}/flow/{flow_id}")
    print(f"  Flow ID:  {flow_id}")
    print()
    print("  NEXT STEPS:")
    print("  1. Open the flow URL above in browser")
    print("  2. You should see 4 nodes: ChatInput → Prompt → Groq → ChatOutput")
    print("  3. Click the Groq node → paste your GROQ_API_KEY")
    print("  4. Click ▶ Play in top-right to test in Playground")
    print("  5. Once working, your backend will auto-route through it")
    print()
    print("  NOTE: If nodes don't appear visually, drag from sidebar:")
    print("    - Inputs > Chat Input")
    print("    - Prompts > Prompt")
    print("    - Models > Groq")
    print("    - Outputs > Chat Output")
    print("  Then connect them with edges and save.")
    print()


if __name__ == "__main__":
    main()
