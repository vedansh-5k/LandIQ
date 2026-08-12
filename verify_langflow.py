"""
verify_langflow.py
------------------
End-to-end check of the Langflow layer. Run this before showing sir.

    python verify_langflow.py

Every line prints PASS / FAIL / SKIP with the reason, so you know exactly
what is real and what is not. Nothing here writes to your project except
the self-healing flow-id lookup.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LANDIQ = "http://127.0.0.1:8000"

passes, fails = 0, 0


def report(label: str, ok: bool, detail: str = "") -> bool:
    global passes, fails
    tag = "PASS" if ok else "FAIL"
    if ok:
        passes += 1
    else:
        fails += 1
    print(f"  [{tag}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def skip(label: str, detail: str = "") -> None:
    print(f"  [SKIP] {label}" + (f" — {detail}" if detail else ""))


def get(path: str, timeout: float = 30.0):
    with httpx.Client(timeout=timeout) as c:
        r = c.get(LANDIQ + path)
        return r.status_code, (r.json() if "json" in r.headers.get("content-type", "") else r.text)


def post(path: str, body: dict, timeout: float = 180.0):
    with httpx.Client(timeout=timeout) as c:
        r = c.post(LANDIQ + path, json=body)
        return r.status_code, (r.json() if "json" in r.headers.get("content-type", "") else r.text)


def main() -> int:
    print("\nLandIQ — Langflow verification")
    print("=" * 58)

    # 1 — bridge imports cleanly
    print("\n1. Bridge module")
    try:
        from src.utils import langflow_bridge as lf
        report("src/utils/langflow_bridge.py imports", True)
    except Exception as e:
        report("src/utils/langflow_bridge.py imports", False, str(e))
        print("\nFix this first — the file is missing or in the wrong folder.")
        return 1

    try:
        from src.utils import langflow_routes  # noqa: F401
        report("src/utils/langflow_routes.py imports", True)
    except Exception as e:
        report("src/utils/langflow_routes.py imports", False, str(e))

    # 2 — api.py patched
    print("\n2. api.py registration")
    api = ROOT / "api.py"
    if api.exists():
        src = api.read_text(encoding="utf-8", errors="ignore")
        report("Langflow router block present in api.py",
               "LANGFLOW_ROUTER_BLOCK" in src or "langflow_router" in src,
               "run: python patch_api_langflow.py")
    else:
        report("api.py found", False, "run from the project root")

    # 3 — LandIQ backend up
    print("\n3. LandIQ backend (port 8000)")
    try:
        code, _ = get("/health", timeout=8)
        backend_up = report("LandIQ responds", code == 200, f"HTTP {code}")
    except Exception as e:
        backend_up = report("LandIQ responds", False, f"{type(e).__name__} — start it with: python run.py")

    if not backend_up:
        print("\nStart LandIQ (python run.py) and run this again.")
        return 1

    # 4 — the endpoint that was 404ing
    print("\n4. Langflow endpoints")
    code, status = get("/langflow/status", timeout=30)
    if not report("GET /langflow/status", code == 200, f"HTTP {code}"):
        print("     -> run: python patch_api_langflow.py, then restart python run.py")
        return 1

    for path in ("/langflow/config", "/langflow/health", "/langflow/flows"):
        c, _ = get(path, timeout=20)
        report(f"GET {path}", c == 200, f"HTTP {c}")

    # 5 — Langflow server itself
    print("\n5. Langflow server (port 7860)")
    lf_state = status.get("langflow", {}) if isinstance(status, dict) else {}
    online = report("Langflow reachable", bool(lf_state.get("online")),
                    lf_state.get("error") or lf_state.get("base_url", ""))
    if online:
        print(f"         version {lf_state.get('version')} at {lf_state.get('base_url')}")

    agents = status.get("agents_detected", []) if isinstance(status, dict) else []
    report("Agents discovered from registry", len(agents) > 0,
           f"{len(agents)} agents: {', '.join(agents[:6])}{'...' if len(agents) > 6 else ''}")

    if not online:
        skip("Flow resolution", "Langflow offline — LandIQ will use the local orchestrator")
        skip("Flow execution", "Langflow offline")
        print("\n  This is not a broken build. LandIQ is designed to keep working")
        print("  with the local orchestrator when Langflow is down.")
        print(f"\n{passes} passed, {fails} failed")
        return 0 if fails == 0 else 1

    # 6 — flow present
    print("\n6. LandIQ flow inside Langflow")
    flow = status.get("flow", {})
    has_flow = report("Flow resolved", bool(flow.get("ok")),
                      f"{flow.get('flow_name')} ({flow.get('source')})"
                      if flow.get("ok") else flow.get("error", ""))
    if flow.get("healed"):
        print("         note: stored flow id was stale and was auto-corrected")
    if has_flow:
        g = status.get("graph", {})
        report("Flow graph readable", g.get("nodes", 0) > 0,
               f"{g.get('nodes')} nodes, {g.get('edges')} edges")
    else:
        print("     -> run: python setup_langflow.py")
        print(f"\n{passes} passed, {fails} failed")
        return 1

    # 7 — real execution
    print("\n7. Live execution through Langflow")
    t0 = time.time()
    code, plan = post("/langflow/plan", {
        "query": "Is 250 sq yards in Gurugram Sector 79 a good buy for a 5 year hold?"
    }, timeout=180)
    took = round(time.time() - t0, 1)

    if code != 200 or not isinstance(plan, dict):
        report("POST /langflow/plan", False, f"HTTP {code}")
    elif plan.get("ok"):
        report("Langflow produced an execution plan", True, f"{took}s")
        layers = plan["plan"]["layers"]
        for i, layer in enumerate(layers, 1):
            print(f"         layer {i}: {', '.join(layer)}")
        if plan["plan"].get("reasoning"):
            print(f"         reasoning: {plan['plan']['reasoning'][:100]}")
        known = set(plan.get("available_agents", []))
        flat = [a for l in layers for a in l]
        report("Plan uses only real registered agents",
               all(a in known for a in flat), f"{len(flat)} agents planned")
    else:
        report("Langflow produced an execution plan", False, plan.get("error", ""))
        if plan.get("raw_text"):
            print(f"         model said: {plan['raw_text'][:160]}")
        print("     -> open the flow in Langflow and check the model's API key")

    print("\n" + "=" * 58)
    print(f"{passes} passed, {fails} failed")
    if fails == 0:
        print("\nEverything is live. Open http://127.0.0.1:8000/static/langflow.html")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
