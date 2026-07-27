"""
fix_landiq_3.py — run in project root, then: python run.py

Fixes:
  1. NameError: session_start not defined  (defines it at start of analyse_land)
  2. max_tokens passed twice -> due_diligence + senior_consultant crash
     (the router chat path passes max_tokens explicitly AND inside **kwargs)
"""
import os, re, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
BK = f".bak3_{int(time.time())}"

def backup(p):
    if os.path.exists(p):
        shutil.copy2(p, p + BK)
        print(f"  backed up: {os.path.basename(p)}")

# ─────────────────────────────────────────────────────────────
# FIX 1 — define session_start inside analyse_land
# ─────────────────────────────────────────────────────────────
def fix_session_start():
    path = os.path.join(ROOT, "api.py")
    c = open(path, "r", encoding="utf-8").read()
    backup(path)

    if "session_start = time.time()" in c:
        print("  session_start already defined")
    else:
        # Insert right after the analyse_land function signature line
        # Find: async def analyse_land(req: LandQueryRequest):
        m = re.search(r'(async def analyse_land\(req: LandQueryRequest\):\n)', c)
        if m:
            insert_at = m.end()
            # find where the first real statement starts (skip the _safe_dump def block)
            # Simplest: add session_start right after the signature, before anything else
            c = c[:insert_at] + "    session_start = time.time()\n" + c[insert_at:]
            print("  inserted 'session_start = time.time()' at top of analyse_land")
        else:
            print("  ⚠ could not find analyse_land signature")

    open(path, "w", encoding="utf-8").write(c)
    print("  api.py saved")

# ─────────────────────────────────────────────────────────────
# FIX 2 — max_tokens duplication in the router chat path
# The RouterChatModel calls router.completion(..., max_tokens=X, **kwargs)
# where kwargs ALSO has max_tokens. Fix: pop it from kwargs before the call.
# Search all likely files.
# ─────────────────────────────────────────────────────────────
def fix_max_tokens():
    files = []
    for root, _, names in os.walk(os.path.join(ROOT, "src")):
        for n in names:
            if n.endswith(".py"):
                files.append(os.path.join(root, n))

    fixed = False
    for path in files:
        c = open(path, "r", encoding="utf-8").read()
        orig = c

        # Look for lines calling .completion( or .acompletion( that include both
        # max_tokens= and **kwargs (or **params, **gen_kwargs, etc.)
        lines = c.split("\n")
        for i, line in enumerate(lines):
            if ("router.completion(" in line or "router.acompletion(" in line
                or ".completion(" in line or ".acompletion(" in line):
                if "max_tokens" in line and "**" in line:
                    # find the **name
                    kwm = re.search(r'\*\*(\w+)', line)
                    if kwm:
                        kw = kwm.group(1)
                        indent = line[:len(line) - len(line.lstrip())]
                        guard = f"{indent}{kw}.pop('max_tokens', None)  # avoid duplicate max_tokens"
                        # insert guard before this line if not already there
                        if i > 0 and "pop('max_tokens'" not in lines[i-1]:
                            lines[i] = guard + "\n" + line
                            fixed = True
                            print(f"  patched {os.path.basename(path)} line {i+1}: pop max_tokens from **{kw}")
        c = "\n".join(lines)

        if c != orig:
            backup(path)
            open(path, "w", encoding="utf-8").write(c)

    # Also handle the multi-line call case: max_tokens on one line, **kwargs on another
    if not fixed:
        for path in files:
            c = open(path, "r", encoding="utf-8").read()
            # find a completion(...) spanning multiple lines with both tokens
            pat = re.compile(
                r'((?:router\.)?a?completion\(\s*(?:[^()]*\n)*?[^()]*?)\*\*(\w+)\s*\)',
                re.MULTILINE
            )
            def check_and_fix(m):
                block = m.group(0)
                kw = m.group(2)
                if "max_tokens" in block:
                    # add a pop just before this statement — but that's hard inline.
                    return block  # leave for manual
                return block
            # We won't auto-edit multi-line here to avoid breakage; just report.

    if not fixed:
        print("  ⚠ Did not find a single-line completion() with max_tokens + **kwargs.")
        print("    The duplication is likely in a multi-line call inside RouterChatModel.")
        print("    Searching for the file that defines RouterChatModel...")
        for path in files:
            c = open(path, "r", encoding="utf-8").read()
            if "RouterChatModel" in c and ("completion(" in c):
                print(f"    -> Found RouterChatModel in: {path}")
                # Show the completion call lines
                for i, ln in enumerate(c.split("\n")):
                    if "completion(" in ln or "max_tokens" in ln:
                        print(f"       line {i+1}: {ln.strip()[:90]}")
    return fixed


if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  LandIQ FIX v3")
    print("=" * 55)
    print(f"\n  root: {ROOT}\n")

    print("  [1/2] Defining session_start in api.py…")
    fix_session_start()

    print("\n  [2/2] Fixing max_tokens duplication…")
    fix_max_tokens()

    print("\n" + "=" * 55)
    print("  DONE. Run: python run.py")
    print("=" * 55 + "\n")
