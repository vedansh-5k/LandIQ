"""
fix_api_paste.py
----------------
Repairs api.py automatically.

What it does:
  1. Backs up api.py -> api.py.bak
  2. Deletes EVERYTHING after `if __name__ == "__main__":`
     (that is where the block was wrongly pasted)
  3. Re-inserts the block in the correct place - ABOVE that line
  4. Restores a clean entry point
  5. Compiles the result to prove there is no syntax error
     (if it fails, api.py is restored from backup and nothing breaks)

Run from project root:
    python fix_api_paste.py
"""

import pathlib
import shutil
import sys

API = pathlib.Path("api.py")
MARKER = 'if __name__ == "__main__":'

BLOCK = '''

# >>> LANDIQ_LANGFLOW_BLOCK_START
# =====================================================================
#  LANDIQ REGISTRY + LANGFLOW SUPPORT ENDPOINTS
#  Added by fix_api_paste.py - do not move below __main__
# =====================================================================

_REGISTRY_DIR = _Path("agents_registry")


def _safe_agent_name(name: str) -> str:
    if not name or "/" in name or "\\\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid agent name")
    return name


@app.get("/registry/agents")
def registry_list_agents():
    """Every agent folder currently present in agents_registry/."""
    agents = []
    if _REGISTRY_DIR.exists():
        for d in sorted(_REGISTRY_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith((".", "_")):
                agents.append({
                    "name": d.name,
                    "agent_md": (d / "AGENT.md").exists(),
                    "skill_md": (d / "SKILL.md").exists(),
                })
    return {
        "count": len(agents),
        "source": str(_REGISTRY_DIR.resolve()),
        "agents": agents,
    }


@app.get("/registry/agents/{agent_name}")
def registry_agent_detail(agent_name: str):
    """Live metadata for one agent, parsed straight from its markdown files."""
    agent_name = _safe_agent_name(agent_name)
    d = _REGISTRY_DIR / agent_name
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="Agent '%s' not found" % agent_name)

    def _read(p, limit=1500):
        try:
            return p.read_text(encoding="utf-8", errors="ignore")[:limit]
        except Exception:
            return ""

    agent_md = _read(d / "AGENT.md")
    skill_md = _read(d / "SKILL.md")

    display = agent_name.replace("_", " ").replace("-", " ").title()
    for line in agent_md.splitlines():
        s = line.strip()
        if s.startswith("#"):
            display = s.lstrip("#").strip() or display
            break

    return {
        "status": "loaded",
        "agent": agent_name,
        "display_name": display,
        "loaded_from": str(d.resolve()),
        "files": sorted(p.name for p in d.iterdir() if p.is_file()),
        "agent_md_preview": agent_md[:700],
        "skill_md_preview": skill_md[:700],
    }


LANGFLOW_BASE = os.getenv("LANGFLOW_BASE_URL", "http://127.0.0.1:7860")


def _landiq_flow_id() -> str:
    p = _Path("langflow_flow_id.txt")
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return os.getenv("LANGFLOW_FLOW_ID", "")


@app.get("/langflow/diag")
async def langflow_diag():
    """Dependency-free Langflow health check. Never 500s."""
    fid = _landiq_flow_id()
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get("%s/health" % LANGFLOW_BASE)
        online = r.status_code < 400
    except Exception as e:
        return {"online": False, "base_url": LANGFLOW_BASE, "flow_id": fid,
                "mode": "local_orchestrator", "error": str(e)[:200]}
    return {
        "online": online,
        "base_url": LANGFLOW_BASE,
        "flow_id": fid,
        "ui_url": ("%s/flow/%s" % (LANGFLOW_BASE, fid)) if fid else LANGFLOW_BASE,
        "mode": "langflow" if (online and fid) else "local_orchestrator",
    }


@app.get("/langflow/flows")
async def langflow_list_flows():
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("%s/api/v1/flows/" % LANGFLOW_BASE)
        data = r.json() if r.status_code < 400 else []
        if isinstance(data, dict):
            data = data.get("items") or data.get("flows") or []
        return {"success": True, "count": len(data),
                "flows": [{"id": f.get("id"), "name": f.get("name")} for f in data]}
    except Exception as e:
        return {"success": False, "count": 0, "flows": [], "error": str(e)[:200]}

# =====================================================================
#  END LANDIQ REGISTRY + LANGFLOW SUPPORT ENDPOINTS
# =====================================================================
# <<< LANDIQ_LANGFLOW_BLOCK_END

'''

TAIL = '''
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''


def main():
    if not API.exists():
        print("\n[X] api.py not found. Run this from the project root folder.")
        sys.exit(1)

    src = API.read_text(encoding="utf-8")

    if MARKER not in src:
        print('\n[X] Could not find the line: if __name__ == "__main__":')
        sys.exit(1)

    # already patched? strip the old copy so re-running is always safe
    START = "# >>> LANDIQ_LANGFLOW_BLOCK_START"
    END = "# <<< LANDIQ_LANGFLOW_BLOCK_END"
    while START in src and END in src and src.index(START) < src.index(END):
        a = src.index(START)
        b = src.index(END) + len(END)
        src = src[:a] + src[b:]
        print("[i] removed a previous copy of the block")

    head = src[:src.index(MARKER)].rstrip() + "\n"
    new_src = head + BLOCK + TAIL

    # prove it parses before touching the real file
    try:
        compile(new_src, "api.py", "exec")
    except SyntaxError as e:
        print("\n[X] Patch would create a syntax error - nothing was written.")
        print("    line %s: %s" % (e.lineno, e.msg))
        sys.exit(1)

    shutil.copy(API, "api.py.bak")
    API.write_text(new_src, encoding="utf-8")

    print("\n" + "=" * 60)
    print("  api.py patched successfully")
    print("=" * 60)
    print("  backup      : api.py.bak")
    print("  new routes  : GET /registry/agents")
    print("                GET /registry/agents/{name}")
    print("                GET /langflow/diag")
    print("                GET /langflow/flows")
    print("\n  Now restart the backend:  python run.py")
    print("  Then open: http://127.0.0.1:8000/registry/agents")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
