"""
agent_registry_manager.py  — v2
Writes agents in EXACT format agent_loader.py expects:
  agents_registry/<name>/AGENT.md
  agents_registry/<name>/SKILL.md

Uses same REGISTRY_DIR calculation as agent_loader.py so paths always match.
"""

import os
import re
import shutil
import httpx
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

# ── SAME path logic as agent_loader.py ────────────────────────────────────────
# agent_loader.py is at src/utils/agent_loader.py
# This file is at src/utils/agent_registry_manager.py  (same folder)
# Both go 3 levels up: src/utils -> src -> project_root
REGISTRY_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
)))) / "agents_registry"
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

# Keep AGENTS_DIR as alias for backward compat
AGENTS_DIR = REGISTRY_DIR


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", text.lower().strip())[:40]
    return s.strip("_") or "agent"


# ── Parse any markdown to agent fields ────────────────────────────────────────

def parse_markdown_to_agent(md_text: str, fallback_name: str = "new_agent") -> dict:
    lines = md_text.strip().splitlines()
    frontmatter = {}
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" in line:
                k, _, v = line.partition(":")
                frontmatter[k.strip().lower()] = v.strip()

    name = (frontmatter.get("name") or frontmatter.get("agent_name")
            or _extract_heading(lines, 1) or fallback_name)
    description = (frontmatter.get("description") or _first_paragraph(md_text)
                   or "Auto-imported agent")
    capabilities = _extract_section(md_text, ("capabilities","skills","what it does","features","workflow"))
    output_format = _extract_section(md_text, ("output","output format","returns","outputs"))

    return {
        "name": _slugify(name),
        "display_name": frontmatter.get("display_name") or name,
        "description": description,
        "capabilities": capabilities or description,
        "output_format": output_format or "Structured analysis with key findings",
        "raw_md": md_text,
    }


def _extract_heading(lines, level=1):
    prefix = "#" * level + " "
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _first_paragraph(text):
    in_front = False
    for block in text.split("\n\n"):
        s = block.strip()
        if s == "---":
            in_front = not in_front
            continue
        if in_front:
            continue
        if s and not s.startswith("#") and not s.startswith("```"):
            return s[:300]
    return None


def _extract_section(text, headings):
    lines = text.splitlines()
    capture, collected = False, []
    for line in lines:
        lower = line.lower().lstrip("#").strip()
        if any(lower == h for h in headings):
            capture = True
            continue
        if capture:
            if line.startswith("#"):
                break
            collected.append(line)
    result = "\n".join(collected).strip()
    return result[:500] if result else None


# ── GitHub fetch ───────────────────────────────────────────────────────────────

async def fetch_github_url(url: str) -> str:
    raw = _to_raw(url)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(raw)
        r.raise_for_status()
        return r.text


def _to_raw(url: str) -> str:
    if "raw.githubusercontent.com" in url:
        return url
    url = url.replace("github.com", "raw.githubusercontent.com")
    url = url.replace("/blob/", "/")
    return url


# ── Save agent — writes folder/AGENT.md + folder/SKILL.md ─────────────────────

def save_agent(name, display_name, description, capabilities,
               output_format, raw_md="", extra_instructions="") -> Path:
    """
    Creates agents_registry/<slug>/AGENT.md + SKILL.md
    in exact format agent_loader.py expects.
    Registers in DB so it shows up in /agents endpoint immediately.
    Returns the folder Path.
    """
    slug = _slugify(name)
    folder = REGISTRY_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)

    # ── AGENT.md ──────────────────────────────────────────────────────────────
    role_text = (
        extra_instructions.strip()
        or (f"You are an expert {display_name} specialising in Indian land investment analysis. "
            f"{description} "
            f"Analyse the provided land parcel data and return a thorough structured assessment.")
    )

    agent_md = f"""---
name: {slug}
display_name: {display_name}
description: {description}
temperature: 0.3
layer: 2
output_fields:
  - {{name: summary,        type: str, description: Overall analysis summary}}
  - {{name: risk_level,     type: str, description: Risk level Low/Medium/High}}
  - {{name: key_findings,   type: str, description: Key findings and insights}}
  - {{name: recommendation, type: str, description: Specific recommendation}}
---
{role_text}
"""

    # ── SKILL.md ──────────────────────────────────────────────────────────────
    skill_body = capabilities or description
    skill_md = f"""---
name: {slug}-skill
description: Workflow instructions for the {display_name}
---
{skill_body}

## Output Format
{output_format}
"""

    (folder / "AGENT.md").write_text(agent_md, encoding="utf-8")
    (folder / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # ── Register in DB (same as create_agent_at_runtime) ─────────────────────
    try:
        from src.utils.db import get_db_connection
        with get_db_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS custom_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL, display_name TEXT,
                description TEXT, created_at TEXT)""")
            conn.execute(
                "INSERT OR REPLACE INTO custom_agents (name,display_name,description,created_at) VALUES(?,?,?,?)",
                (slug, display_name, description, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
    except Exception:
        pass  # files written — DB failure non-fatal

    return folder


# ── List agents (reads folders with AGENT.md) ─────────────────────────────────

def list_agents() -> list:
    agents = []
    for folder in sorted(REGISTRY_DIR.iterdir()):
        if not folder.is_dir():
            continue
        agent_md = folder / "AGENT.md"
        if not agent_md.exists():
            continue
        text = agent_md.read_text(encoding="utf-8")
        info = parse_markdown_to_agent(text, fallback_name=folder.name)
        info["name"] = folder.name
        info["file"] = folder.name + "/AGENT.md"
        info.pop("raw_md", None)
        agents.append(info)
    return agents


# ── Delete agent ───────────────────────────────────────────────────────────────

def delete_agent(slug: str) -> bool:
    slug = _slugify(slug)
    folder = REGISTRY_DIR / slug
    if folder.exists() and folder.is_dir():
        shutil.rmtree(folder)
        try:
            from src.utils.db import get_db_connection
            with get_db_connection() as conn:
                conn.execute("DELETE FROM custom_agents WHERE name=?", (slug,))
                conn.commit()
        except Exception:
            pass
        return True
    return False