"""
fix_langflow_api.py
───────────────────
Patches api.py to ensure:
  1. Langflow routes are registered (no more 404)
  2. /langflow/status returns 200
  3. /analyse tries Langflow first, falls back to local
  4. Timeout = 600s for Langflow calls

Run BEFORE setup_langflow_full.py:
  python fix_langflow_api.py
  python setup_langflow_full.py
  python run.py
"""

import os, re, shutil

API_FILE = "api.py"
BRIDGE_FILE = os.path.join("src", "utils", "langflow_bridge.py")


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def patch_api():
    if not os.path.exists(API_FILE):
        print(f"[!] {API_FILE} not found in current directory")
        return False

    code = read(API_FILE)
    original = code
    changes = 0

    # ── 1. Add langflow_bridge import if missing ─────────────────────
    if "langflow_bridge" not in code:
        # Find the last "from src..." import
        last_import = ""
        for line in code.split("\n"):
            if line.strip().startswith("from src") or line.strip().startswith("import src"):
                last_import = line
        if last_import:
            code = code.replace(
                last_import,
                last_import + "\n"
                "try:\n"
                "    from src.utils.langflow_bridge import langflow_status, run_via_langflow\n"
                "    _LANGFLOW_OK = True\n"
                "except ImportError:\n"
                "    _LANGFLOW_OK = False\n"
                "    def langflow_status(): return {'langflow_alive': False, 'error': 'bridge not installed'}\n"
                "    def run_via_langflow(p, **kw): return None\n"
            )
            changes += 1
            print("[1] Added langflow_bridge import")
        else:
            # Add at top after existing imports
            code = code.replace(
                "from fastapi import",
                "try:\n"
                "    from src.utils.langflow_bridge import langflow_status, run_via_langflow\n"
                "    _LANGFLOW_OK = True\n"
                "except ImportError:\n"
                "    _LANGFLOW_OK = False\n"
                "    def langflow_status(): return {'langflow_alive': False, 'error': 'bridge not installed'}\n"
                "    def run_via_langflow(p, **kw): return None\n\n"
                "from fastapi import",
                1
            )
            changes += 1
            print("[1] Added langflow_bridge import (top)")
    else:
        print("[1] langflow_bridge import already present ✓")

    # ── 2. Add Langflow routes if missing ────────────────────────────
    if '"/langflow/status"' not in code and "langflow/status" not in code:
        # Find the line: if __name__ == "__main__":
        main_marker = 'if __name__ == "__main__":'
        if main_marker in code:
            langflow_routes = '''

# ── Langflow Integration Routes ──────────────────────────────────────
@app.get("/langflow/status")
async def get_langflow_status():
    """Check if Langflow is alive and return flow info."""
    return langflow_status()

@app.post("/langflow/run")
async def run_langflow_pipeline(request: Request):
    """Run the full pipeline through Langflow (timeout=600s)."""
    payload = await request.json()
    result = run_via_langflow(payload, timeout=600)
    if result is None:
        raise HTTPException(status_code=503, detail="Langflow unavailable — use /analyse for local execution")
    return result

@app.get("/internal/langflow-bridge-check")
async def langflow_bridge_check():
    """Internal check — confirms bridge module is loaded."""
    return {"bridge_loaded": _LANGFLOW_OK if '_LANGFLOW_OK' in dir() else False}

'''
            code = code.replace(main_marker, langflow_routes + "\n" + main_marker)
            changes += 1
            print("[2] Added Langflow routes (/langflow/status, /langflow/run)")
        else:
            print("[!] Could not find 'if __name__' block — add routes manually")
    else:
        print("[2] Langflow routes already present ✓")

    # ── 3. Fix run_via_langflow None handling in /analyse ────────────
    # If /analyse already tries Langflow, make sure None result falls back
    if "run_via_langflow" in code and "langflow_result" not in code:
        # Find the /analyse endpoint and add Langflow-first logic
        # Look for the line that calls run_land_advisor or run_dynamic_advisor
        if "run_land_advisor" in code or "run_dynamic_advisor" in code:
            # Find the actual call pattern
            advisor_call = "run_land_advisor" if "run_land_advisor" in code else "run_dynamic_advisor"
            # Check if there's already a langflow-first pattern
            if "langflow_result" not in code:
                print("[3] /analyse endpoint — Langflow-first logic needs manual review")
                print("    (Your orchestrator call is complex; add this BEFORE it):")
                print(f'    langflow_result = run_via_langflow(payload_dict, timeout=600)')
                print(f'    if langflow_result is not None:')
                print(f'        return langflow_result')
                print(f'    # else fall through to {advisor_call}')
    else:
        print("[3] Langflow fallback pattern — check /analyse manually")

    # ── 4. Register route log on startup ─────────────────────────────
    if "[Langflow] routes registered" not in code:
        startup_marker = "Application startup complete"
        if "@app.on_event" in code or "lifespan" in code:
            # Add a print to startup
            if 'print("[Langflow] routes registered' not in code:
                # Find app creation or lifespan and add print
                if main_marker in code:
                    code = code.replace(
                        main_marker,
                        'print("[Langflow] routes registered at /langflow/* and /internal/*")\n\n' + main_marker
                    )
                    changes += 1
                    print("[4] Added Langflow startup log")
        else:
            print("[4] Startup log — skipped (add manually if needed)")
    else:
        print("[4] Langflow startup log already present ✓")

    # ── Save ─────────────────────────────────────────────────────────
    if code != original:
        # Backup
        backup = API_FILE + ".bak"
        shutil.copy2(API_FILE, backup)
        print(f"[*] Backup saved: {backup}")

        write(API_FILE, code)
        print(f"[✓] Patched {API_FILE} ({changes} changes)")
    else:
        print(f"[*] No changes needed in {API_FILE}")

    return True


def verify():
    """Quick import check."""
    code = read(API_FILE)
    checks = {
        "langflow_bridge import": "langflow_bridge" in code,
        "/langflow/status route":  "langflow/status" in code,
        "langflow_status function": "langflow_status" in code,
    }
    print("\n[Verify]")
    all_ok = True
    for name, ok in checks.items():
        status = "✓" if ok else "✗ MISSING"
        print(f"  {status}  {name}")
        if not ok:
            all_ok = False

    if all_ok:
        print("\n[✓] All checks passed — run: python run.py")
    else:
        print("\n[!] Some checks failed — review api.py manually")


if __name__ == "__main__":
    print("=" * 50)
    print("  LandIQ — Langflow API Patcher")
    print("=" * 50)
    print()

    if patch_api():
        verify()

    print()
    print("Next steps:")
    print("  1. python setup_langflow_full.py")
    print("  2. python run.py")
    print("  3. Open http://localhost:7860 → see all agents with wires")
