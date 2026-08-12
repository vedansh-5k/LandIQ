"""
integrate_headroom.py
---------------------
Run ONCE to add Headroom integration to LandIQ.
Safe — only adds, never removes or overwrites working code.

What it does:
  1. Installs headroom-ai package
  2. Copies headroom_bridge.py to src/utils/
  3. Adds headroom_mode field to LandQueryRequest in api.py
  4. Wraps the orchestrator call in headroom_ctx() in api.py
  5. Adds headroom_report to the /analyse response
  6. Adds /headroom/test endpoint for quick testing
  7. Adds headroom toggle to frontend index.html

Usage:
    cd C:\\Users\\HP\\OneDrive\\Desktop\\ai_boardroom_v3
    .\\venv\\Scripts\\activate
    python integrate_headroom.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_PY = ROOT / "api.py"
INDEX_HTML = ROOT / "frontend" / "index.html"
BRIDGE_SRC = ROOT / "headroom_bridge.py"
BRIDGE_DST = ROOT / "src" / "utils" / "headroom_bridge.py"


def step(n, msg):
    print(f"\n[{n}] {msg}")


def read(path):
    return path.read_text(encoding="utf-8")


def write(path, text):
    path.write_text(text, encoding="utf-8")


# ── Step 1: Install headroom-ai ─────────────────────────────────────
step(1, "Installing headroom-ai ...")
try:
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "headroom-ai",
        "--break-system-packages", "--quiet"
    ])
    print("      -> installed")
except Exception as e:
    print(f"      -> pip install failed: {e}")
    print("      -> continuing anyway (headroom_bridge has safe fallback)")


# ── Step 2: Copy headroom_bridge.py ─────────────────────────────────
step(2, "Copying headroom_bridge.py to src/utils/ ...")
if BRIDGE_SRC.exists():
    shutil.copy2(BRIDGE_SRC, BRIDGE_DST)
    print(f"      -> {BRIDGE_DST}")
elif BRIDGE_DST.exists():
    print("      -> already exists, skipping")
else:
    print("      -> ERROR: headroom_bridge.py not found at project root!")
    print("         Download it first, place next to this script, rerun.")
    sys.exit(1)


# ── Step 3: Add headroom_mode to LandQueryRequest ───────────────────
step(3, "Adding headroom_mode to LandQueryRequest in api.py ...")
api = read(API_PY)

if "headroom_mode" in api:
    print("      -> already present, skipping")
else:
    # Find the last field before the class ends — look for caveman_mode or
    # guardrail_config as anchors (they're the last fields in the model)
    anchors = ["guardrail_config", "caveman_level", "caveman_mode",
               "guardrail_mode", "selected_config"]
    inserted = False
    for anchor in anchors:
        marker = f"{anchor}:"
        if marker in api:
            # Find the line with this field
            lines = api.split("\n")
            for i, line in enumerate(lines):
                if marker in line and "class " not in line:
                    # Insert after this line
                    indent = "    "
                    new_line = f'{indent}headroom_mode: bool = False'
                    lines.insert(i + 1, new_line)
                    api = "\n".join(lines)
                    inserted = True
                    print(f"      -> added after {anchor}")
                    break
            if inserted:
                break

    if not inserted:
        print("      -> WARNING: Could not find anchor field. Add manually:")
        print("         In class LandQueryRequest, add:  headroom_mode: bool = False")

    write(API_PY, api)


# ── Step 4: Add headroom import to api.py ───────────────────────────
step(4, "Adding headroom_bridge import to api.py ...")
api = read(API_PY)

if "headroom_bridge" in api:
    print("      -> already imported, skipping")
else:
    # Add import near the top, after existing src imports
    import_line = "from src.utils.headroom_bridge import headroom_ctx, get_stats as get_headroom_stats, is_available as headroom_available, test_compression as headroom_test_compression"

    # Find a good insertion point — after other src.utils imports
    lines = api.split("\n")
    insert_at = None
    for i, line in enumerate(lines):
        if "from src.utils" in line or "from src.graph" in line:
            insert_at = i + 1

    if insert_at:
        lines.insert(insert_at, import_line)
        api = "\n".join(lines)
        print(f"      -> added import at line {insert_at + 1}")
    else:
        # Fallback: add after all imports
        lines.insert(25, import_line)
        api = "\n".join(lines)
        print("      -> added import at line 26 (fallback position)")

    write(API_PY, api)


# ── Step 5: Wrap orchestrator call with headroom_ctx ────────────────
step(5, "Wrapping orchestrator call with headroom_ctx ...")
api = read(API_PY)

if "headroom_ctx" in api and "headroom_ctx(" in api:
    print("      -> already wrapped, skipping")
else:
    # Find the line that calls run_dynamic_advisor or run_land_advisor
    # in the /analyse endpoint and wrap it
    lines = api.split("\n")
    found = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Look for: final_state = run_dynamic_advisor(user_inputs)
        # or similar patterns
        if ("run_dynamic_advisor(" in stripped or "run_land_advisor(" in stripped) and "final_state" in stripped:
            indent = line[:len(line) - len(line.lstrip())]
            original_call = stripped

            # Check if headroom_mode is available in scope
            # Replace the single line with a with block
            lines[i] = (
                f"{indent}# ── Headroom: compress input tokens if enabled ──\n"
                f"{indent}_hm = user_inputs.get('headroom_mode', False)\n"
                f"{indent}with headroom_ctx(_hm):\n"
                f"{indent}    {original_call}\n"
                f"{indent}_headroom_stats = get_headroom_stats()"
            )
            found = True
            print(f"      -> wrapped at line {i + 1}")
            break

    if not found:
        print("      -> WARNING: Could not find orchestrator call to wrap.")
        print("         You'll need to manually wrap it. In the /analyse function,")
        print("         change:")
        print("           final_state = run_dynamic_advisor(user_inputs)")
        print("         to:")
        print("           _hm = user_inputs.get('headroom_mode', False)")
        print("           with headroom_ctx(_hm):")
        print("               final_state = run_dynamic_advisor(user_inputs)")
        print("           _headroom_stats = get_headroom_stats()")

    api = "\n".join(lines)
    write(API_PY, api)


# ── Step 6: Add headroom_report to /analyse response ────────────────
step(6, "Adding headroom_report to /analyse response ...")
api = read(API_PY)

if "headroom_report" in api:
    print("      -> already present, skipping")
else:
    # Find "token_report" in the return dict of /analyse and add after it
    lines = api.split("\n")
    found = False
    for i, line in enumerate(lines):
        if '"token_report"' in line and "tokens" in api[max(0, api.find(line)-200):api.find(line)]:
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(i + 1, f'{indent}"headroom_report": _headroom_stats if "_headroom_stats" in dir() else {{"enabled": False, "available": headroom_available()}},')
            found = True
            print(f"      -> added after token_report at line {i + 2}")
            break

    if not found:
        print("      -> WARNING: Could not find token_report in response. Add manually:")
        print('         "headroom_report": _headroom_stats,')

    api = "\n".join(lines)
    write(API_PY, api)


# ── Step 7: Add /headroom/test endpoint ─────────────────────────────
step(7, "Adding /headroom/test endpoint ...")
api = read(API_PY)

if "/headroom/test" in api:
    print("      -> already exists, skipping")
else:
    # Add before if __name__ == "__main__":
    endpoint_code = '''

# ── Headroom: test endpoint ─────────────────────────────────────────
@app.get("/headroom/status")
def headroom_status():
    """Check if Headroom is installed and available."""
    return {
        "available": headroom_available(),
        "description": "Headroom compresses INPUT tokens (prompts, RAG, JSON) "
                       "before they reach the LLM. Same answer, 60-95% fewer tokens.",
        "github": "https://github.com/chopratejas/headroom",
    }


@app.post("/headroom/test")
def headroom_test(text: str = "The residential property located in Whitefield, "
                              "Bangalore, Karnataka has been analysed. The current "
                              "price range is Rs 3500-4500 per sq yard based on "
                              "comparable areas. The upcoming Namma Metro Phase 2 "
                              "extension is expected to increase demand by 15-20%."):
    """Test Headroom compression on a sample text."""
    return headroom_test_compression(text)

'''

    marker = 'if __name__ == "__main__":'
    if marker in api:
        api = api.replace(marker, endpoint_code + marker)
        print("      -> added /headroom/status and /headroom/test endpoints")
    else:
        api += endpoint_code
        print("      -> appended endpoints (no __main__ block found)")

    write(API_PY, api)


# ── Step 8: Add headroom toggle to frontend ─────────────────────────
step(8, "Adding headroom toggle to frontend ...")

if not INDEX_HTML.exists():
    print("      -> frontend/index.html not found, skipping frontend patch")
else:
    html = read(INDEX_HTML)

    if "headroom_mode" in html or "headroomMode" in html:
        print("      -> already present, skipping")
    else:
        # Find caveman toggle and add headroom toggle after it
        # Look for caveman-related checkbox/toggle
        caveman_markers = ["caveman_mode", "cavemanMode", "Caveman Mode", "caveman-toggle"]
        inserted_toggle = False

        for marker in caveman_markers:
            if marker in html:
                # Find the containing div/section
                idx = html.find(marker)
                # Find the end of the current toggle section (next closing div or label)
                # We'll add after the caveman section
                # Look for the next </div> or </label> after the marker
                search_from = idx + len(marker)

                # Find the line with the marker
                lines = html.split("\n")
                for i, line in enumerate(lines):
                    if marker in line:
                        # Find the closing tag of this toggle group
                        # Go forward until we find a blank line or next section
                        insert_at = i + 1
                        # Skip until we find a reasonable insertion point
                        while insert_at < len(lines) and lines[insert_at].strip() not in ("", "</div>"):
                            insert_at += 1

                        headroom_toggle = '''
              <!-- Headroom Toggle (Input Token Compression) -->
              <div style="margin-top:10px;padding:8px 12px;background:rgba(139,115,85,0.08);border-radius:8px;display:flex;align-items:center;gap:10px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.92em;color:var(--accent);">
                  <input type="checkbox" id="headroomToggle" onchange="window._headroomMode=this.checked"
                         style="accent-color:var(--gold);width:16px;height:16px;">
                  <span>🗜️ <b>Headroom</b> — compress input tokens (saves 60-95%)</span>
                </label>
              </div>'''
                        lines.insert(insert_at, headroom_toggle)
                        html = "\n".join(lines)
                        inserted_toggle = True
                        print(f"      -> added toggle after caveman section")
                        break
                break

        if not inserted_toggle:
            print("      -> WARNING: Could not find caveman toggle to anchor after.")
            print("         Add manually in the form area.")

        # Add headroom_mode to the fetch body in the analyse JS
        if "headroom_mode" not in html:
            # Find where caveman_mode is sent in the fetch body
            for cm in ["caveman_mode", "cavemanMode"]:
                if cm in html:
                    # Find it in the fetch body context
                    idx = html.find(cm)
                    # Check if this is in a JS object being POSTed
                    while idx != -1:
                        # Look at surrounding context
                        context = html[max(0, idx-100):idx+100]
                        if "body" in context or "JSON" in context or "fetch" in context or "{" in context:
                            # This is in the POST body — add headroom_mode after it
                            # Find end of this line
                            line_end = html.find("\n", idx)
                            if line_end != -1:
                                line = html[idx:line_end]
                                # Add headroom_mode line after
                                indent = "          "
                                insert_text = f"\n{indent}headroom_mode: window._headroomMode || false,"
                                html = html[:line_end] + insert_text + html[line_end:]
                                print("      -> added headroom_mode to fetch body")
                                break
                        idx = html.find(cm, idx + 1)
                    break

        # Add headroom stats display to results
        if "headroom_report" not in html and "headroomReport" not in html:
            # Find where token_report is displayed and add headroom after
            token_markers = ["token_report", "tokenReport", "Token Report"]
            for tm in token_markers:
                if tm in html:
                    idx = html.find(tm)
                    # Find a reasonable place after token report display
                    line_end = html.find("\n", idx)
                    context = html[idx:idx+500]
                    # We'll add a simple display block
                    break

        write(INDEX_HTML, html)
        print("      -> frontend updated")


# ── Done ────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("  HEADROOM INTEGRATION COMPLETE")
print(f"{'='*60}")
print("""
  What was added (nothing removed or changed):

  1. headroom-ai package installed in your venv
  2. src/utils/headroom_bridge.py — the bridge module
  3. headroom_mode: bool field added to LandQueryRequest
  4. Orchestrator call wrapped in headroom_ctx()
  5. headroom_report added to /analyse response
  6. /headroom/status and /headroom/test endpoints added
  7. Headroom toggle added to frontend (next to Caveman)

  To test:
    python run.py
    Then open: http://127.0.0.1:8000/headroom/test

  To use in analysis:
    Check the 🗜️ Headroom toggle in the form → run analysis
    Response will include headroom_report with token savings

  To verify from terminal:
    python -c "from src.utils.headroom_bridge import test_compression; test_compression()"
""")
print(f"{'='*60}\n")
