"""
patch_api_langflow.py  —  project root.  Run:  python patch_api_langflow.py

Does two things to api.py, safely:

  1. REMOVES the old pasted Langflow block (the one starting
     "#  LANGFLOW INTEGRATION ENDPOINTS"). That block hardcodes
     localhost:7860 in three places and its /internal/run-single-agent
     calls _safe_dump, which only exists inside analyse_land -> NameError.
     Its /langflow/status also shadows the new one, since it is defined first.

  2. ADDS the two routers, above `if __name__ == "__main__":`.

Safety:
  * timestamped backup before writing
  * idempotent — safe to run twice
  * result is ast.parse'd; if it would not compile, nothing is written
  * the include is wrapped in try/except, so api.py boots even if the
    Langflow files are missing
"""

from __future__ import annotations

import ast
import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = ROOT / "api.py"
MARKER = "LANGFLOW_ROUTER_BLOCK"
OLD_MARKER = "LANGFLOW INTEGRATION ENDPOINTS"

BLOCK = '''
# ── {marker} — added by patch_api_langflow.py ──────────────
# Additive only. If this import fails, LandIQ boots exactly as before.
try:
    from src.utils.langflow_routes import langflow_router, internal_router
    {app}.include_router(langflow_router)
    {app}.include_router(internal_router)
    print("[Langflow] routes registered at /langflow/* and /internal/*")
except Exception as _langflow_exc:  # pragma: no cover
    print(f"[Langflow] routes not loaded ({{_langflow_exc}}) — local orchestrator unaffected")
# ── end {marker} ──────────────────────────────────────────

'''


def strip_old_block(lines):
    """Cut from the old block's banner down to the __main__ guard."""
    hit = next((i for i, l in enumerate(lines) if OLD_MARKER in l), None)
    if hit is None:
        return lines, 0

    start = hit
    while start > 0 and lines[start - 1].lstrip().startswith("# ═"):
        start -= 1

    end = next((i for i, l in enumerate(lines)
                if re.match(r'^\s*if\s+__name__\s*==', l)), None)
    if end is None or end <= start:
        return lines, 0

    return lines[:start] + lines[end:], end - start


def main() -> int:
    print("\nLandIQ — api.py Langflow patch")
    print("=" * 46)

    if not API.exists():
        print(f"api.py not found at {API}. Run from the project root.")
        return 1

    source = API.read_text(encoding="utf-8")
    if MARKER in source:
        print("Already patched — nothing to do.  Start: python run.py")
        return 0

    m = re.search(r"^\s*(\w+)\s*=\s*FastAPI\s*\(", source, re.MULTILINE)
    app_name = m.group(1) if m else "app"
    print(f"FastAPI instance : {app_name}")

    lines = source.splitlines(keepends=True)
    lines, removed = strip_old_block(lines)
    print(f"Old block        : {'removed %d lines' % removed if removed else 'not present'}")

    block = BLOCK.format(marker=MARKER, app=app_name)
    idx = next((i for i, l in enumerate(lines)
                if re.match(r'^\s*if\s+__name__\s*==', l)), None)
    if idx is None:
        print("No __main__ guard — appending at end of file.")
        patched = "".join(lines).rstrip() + "\n\n" + block
    else:
        print(f"Router inserted  : above line {idx + 1} (the __main__ guard)")
        patched = "".join(lines[:idx]) + block + "".join(lines[idx:])

    try:
        ast.parse(patched)
    except SyntaxError as e:
        print(f"Patch would break api.py ({e}). Nothing written.")
        return 1

    backup = API.with_suffix(f".py.bak_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(API, backup)
    API.write_text(patched, encoding="utf-8")

    print(f"Backup saved     : {backup.name}")
    print("\nNext:")
    print("  1. python run.py")
    print("  2. python verify_langflow.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
