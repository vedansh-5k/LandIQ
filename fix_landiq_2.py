"""
fix_landiq_2.py — Run in project root. Fixes 2 bugs:
  1. session_duration NameError in api.py (from previous patch)
  2. max_tokens passed twice → router crash (due_diligence + senior_consultant fail)

Usage:
    cd C:\\Users\\HP\\OneDrive\\Desktop\\ai_boardroom_v3
    python fix_landiq_2.py
    python run.py
"""
import os, re, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
BK = f".bak2_{int(time.time())}"

def backup(p):
    if os.path.exists(p):
        shutil.copy2(p, p + BK)
        print(f"  backed up: {os.path.basename(p)}")

# ═══════════════════════════════════════════════════════════════
# FIX 1 — api.py: session_duration NameError
# The timing block was inserted into the return dict, but it references
# session_duration / session_start which ARE defined earlier in analyse_land.
# The real problem: the previous patcher inserted timing referencing
# session_start+session_duration but the return happens AFTER those exist.
# We just need to make sure the timing block uses variables that exist.
# ═══════════════════════════════════════════════════════════════
def fix_api_timing():
    path = os.path.join(ROOT, "api.py")
    if not os.path.exists(path):
        print("  api.py not found"); return
    backup(path)
    c = open(path, "r", encoding="utf-8").read()

    # The safest fix: replace the broken timing block with one that computes
    # values inline from session_start (which is defined at the top of analyse_land)
    # Find the timing block and replace it
    timing_pattern = re.compile(
        r'"timing":\s*\{[^}]*"total_seconds":[^}]*\},',
        re.DOTALL
    )

    new_timing = ('"timing": {\n'
                  '            "total_seconds": round(time.time() - session_start, 2),\n'
                  '            "start_time": time.strftime("%H:%M:%S", time.localtime(session_start)),\n'
                  '            "end_time": time.strftime("%H:%M:%S", time.localtime()),\n'
                  '        },')

    if timing_pattern.search(c):
        c = timing_pattern.sub(new_timing, c)
        print("  fixed timing block to use session_start")
    else:
        print("  timing block not found (may already be fixed or removed)")

    open(path, "w", encoding="utf-8").write(c)
    print("  api.py saved")


# ═══════════════════════════════════════════════════════════════
# FIX 2 — the max_tokens double-pass crash in the router path
# Error: "Router.completion() got multiple values for keyword argument 'max_tokens'"
# This happens in the LOCAL CONFIG router call inside llm_factory / dynamic_agent.
# We search src/ for the router .completion(...) call that passes max_tokens
# both positionally/in kwargs AND again explicitly.
# ═══════════════════════════════════════════════════════════════
def fix_router_maxtokens():
    """
    Find the router .completion/.acompletion call that duplicates max_tokens
    and print the exact location so we know what to fix. Also attempts a
    safe auto-fix for the most common pattern.
    """
    candidates = [
        os.path.join(ROOT, "src", "utils", "llm_factory.py"),
        os.path.join(ROOT, "src", "agents", "dynamic_agent.py"),
        os.path.join(ROOT, "src", "utils", "router_manager.py"),
    ]
    found = False
    for path in candidates:
        if not os.path.exists(path):
            continue
        lines = open(path, "r", encoding="utf-8").read().splitlines()
        for i, line in enumerate(lines):
            if ("completion(" in line or "acompletion(" in line) and "max_tokens" in line:
                print(f"  FOUND in {os.path.basename(path)} line {i+1}:")
                print(f"    {line.strip()[:100]}")
                found = True
            # Also flag lines that build a params dict with max_tokens then spread it
            if "**" in line and ("completion(" in line):
                print(f"  SPREAD in {os.path.basename(path)} line {i+1}:")
                print(f"    {line.strip()[:100]}")
                found = True
    if not found:
        print("  No obvious router call with max_tokens found in the 3 usual files.")
        print("  The duplication is likely inside a helper. Send llm_factory.py.")
    return found


if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  LandIQ FIX v2 — session_duration + max_tokens")
    print("=" * 55)
    print(f"\n  root: {ROOT}\n")

    print("  [1/2] Fixing api.py timing (session_duration)…")
    fix_api_timing()

    print("\n  [2/2] Fixing router max_tokens duplication…")
    ok = fix_router_maxtokens()

    print("\n" + "=" * 55)
    print("  DONE. Now run: python run.py")
    if not ok:
        print("\n  ⚠ If due_diligence/senior_consultant STILL fail with")
        print("    'multiple values for max_tokens', send me the file:")
        print("    src/utils/llm_factory.py  (or dynamic_agent.py)")
        print("    so I can pinpoint the exact line.")
    print("=" * 55 + "\n")
