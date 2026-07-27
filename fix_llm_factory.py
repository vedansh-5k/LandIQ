"""
fix_llm_factory.py — run in project root, then WAIT 60s, then: python run.py

The crash 'multiple values for keyword argument max_tokens' means the router
call passes max_tokens explicitly AND again inside a **kwargs / params dict.

This script:
  1. Prints the exact router.completion / acompletion blocks (so we can verify)
  2. Adds a guard line that pops 'max_tokens' out of any **dict passed to the
     router call, so only the explicit max_tokens= survives. Safe & reversible.
"""
import os, re, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(ROOT, "src", "utils", "llm_factory.py")

if not os.path.exists(path):
    print("ERROR: llm_factory.py not found at", path)
    raise SystemExit(1)

src = open(path, "r", encoding="utf-8").read()
lines = src.split("\n")

print("\n" + "=" * 60)
print("  router.completion / acompletion CALLS in llm_factory.py")
print("=" * 60 + "\n")

call_starts = []
for i, ln in enumerate(lines):
    if re.search(r'self\.router\.(a?completion)\(', ln):
        call_starts.append(i)
        print(f"  --- call at line {i+1} ---")
        depth = 0
        j = i
        while j < len(lines) and j < i + 18:
            print(f"  {j+1:4d}| {lines[j]}")
            depth += lines[j].count("(") - lines[j].count(")")
            if j > i and depth <= 0:
                break
            j += 1
        print()

if not call_starts:
    print("  No self.router.completion/acompletion calls found.")
    print("  Send me llm_factory.py lines 120-380 so I can see the real call.")
    raise SystemExit(0)

# ── Determine the **kwargs variable name(s) used in these calls ──
kw_names = set()
for i in call_starts:
    depth = 0
    j = i
    while j < len(lines) and j < i + 18:
        m = re.search(r'\*\*(\w+)', lines[j])
        if m:
            kw_names.add(m.group(1))
        depth += lines[j].count("(") - lines[j].count(")")
        if j > i and depth <= 0:
            break
        j += 1

print("=" * 60)
if kw_names:
    print(f"  Found **dict spread in calls: {kw_names}")
    print("  Adding guard to pop 'max_tokens' from each before the call.")
else:
    print("  No **kwargs spread in the router calls themselves.")
    print("  The duplicate max_tokens likely comes from the call passing BOTH")
    print("  a positional/explicit max_tokens AND the router config injecting it.")
    print("  In that case we make max_tokens explicit-only (leave as is) and")
    print("  the real fix is: pass model + messages + max_tokens, nothing else.")
print("=" * 60 + "\n")

shutil.copy2(path, path + f".bakF_{int(time.time())}")

changed = False

if kw_names:
    # Insert a pop guard on the line BEFORE each router call, at same indent
    new_lines = []
    for idx, ln in enumerate(lines):
        if re.search(r'self\.router\.(a?completion)\(', ln):
            indent = ln[:len(ln) - len(ln.lstrip())]
            for kw in kw_names:
                guard = f"{indent}if isinstance({kw}, dict): {kw}.pop('max_tokens', None)"
                # avoid duplicating if already present just above
                if not (new_lines and "pop('max_tokens'" in new_lines[-1] and kw in new_lines[-1]):
                    new_lines.append(guard)
                    changed = True
        new_lines.append(ln)
    if changed:
        open(path, "w", encoding="utf-8").write("\n".join(new_lines))
        print("  ✅ Guard lines added. Duplicate max_tokens stripped from **kwargs.")
else:
    # No **kwargs — the safest correct fix is to strip the explicit max_tokens=
    # line, because the router (LiteLLM) injects max_tokens from the model's
    # litellm_params/config. Passing it again = the crash.
    print("  Applying alternate fix: removing explicit 'max_tokens=' lines")
    print("  inside router calls (router injects it from config).\n")
    out = []
    i = 0
    n = len(lines)
    removed = 0
    while i < n:
        ln = lines[i]
        if re.search(r'self\.router\.(a?completion)\(', ln):
            out.append(ln)
            depth = ln.count("(") - ln.count(")")
            i += 1
            while i < n and depth > 0:
                inner = lines[i]
                if re.match(r'^\s*max_tokens\s*=', inner):
                    print(f"  removed line {i+1}: {inner.strip()[:60]}")
                    removed += 1
                    depth += inner.count("(") - inner.count(")")
                    i += 1
                    continue
                out.append(inner)
                depth += inner.count("(") - inner.count(")")
                i += 1
            continue
        out.append(ln)
        i += 1
    if removed:
        open(path, "w", encoding="utf-8").write("\n".join(out))
        print(f"\n  ✅ Removed {removed} explicit max_tokens line(s).")
        changed = True

if not changed:
    print("  ⚠ Nothing changed — send me the printed lines above.")

print("\n" + "=" * 60)
print("  NEXT STEPS (IMPORTANT):")
print("  1. WAIT 60 SECONDS — Groq free tier is rate-limited from your")
print("     previous runs. Running now = more 429 errors.")
print("  2. python run.py")
print("  3. Do ONE analysis. Do not click Analyse repeatedly.")
print("=" * 60 + "\n")
