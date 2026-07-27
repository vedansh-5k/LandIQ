"""
agent_loader.py
---------------
Scans the agents_registry/ folder, parses AGENT.md + SKILL.md files,
and builds the agent catalogue.

This is the "progressive disclosure" engine (same pattern as SKILL.md articles):
  Level 1: get_agent_catalogue()  -> just names + descriptions (cheap, for orchestrator planning)
  Level 2: load_agent(name)       -> full AGENT.md + SKILL.md content (loaded only when agent runs)

Also supports runtime-created agents: create_agent_at_runtime() writes the
two .md files AND a DB row, making the new agent instantly available.
"""

import os
import re
import json
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# agents_registry/ lives at project root (same level as api.py)
REGISTRY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "agents_registry"
)
os.makedirs(REGISTRY_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────
#  FRONTMATTER PARSER
#  AGENT.md and SKILL.md start with a YAML-style block between --- markers.
#  We parse it without needing the yaml library (keeps dependencies minimal).
# ─────────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple:
    """
    Splits a markdown file into (frontmatter_dict, body_string).
    Frontmatter is the block between the first two '---' lines.
    """
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', text, re.DOTALL)
    if not match:
        return {}, text  # no frontmatter — whole file is body

    raw_front, body = match.group(1), match.group(2)
    front = {}
    current_list_key = None

    for line in raw_front.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # list item:  - {name: x, type: str, description: "..."}
        if stripped.startswith('- ') and current_list_key:
            item_text = stripped[2:].strip()
            if item_text.startswith('{') and item_text.endswith('}'):
                # parse inline dict: {name: area_overview, type: str, description: "..."}
                item = {}
                inner = item_text[1:-1]
                # split on commas not inside quotes
                parts = re.split(r',\s*(?=[a-zA-Z_]+\s*:)', inner)
                for part in parts:
                    if ':' in part:
                        k, v = part.split(':', 1)
                        item[k.strip()] = v.strip().strip('"').strip("'")
                front[current_list_key].append(item)
            else:
                front[current_list_key].append(item_text.strip('"').strip("'"))
            continue

        # key: value
        if ':' in stripped:
            key, value = stripped.split(':', 1)
            key = key.strip()
            value = value.strip()
            if value == '':                       # start of a list
                front[key] = []
                current_list_key = key
            else:
                current_list_key = None
                # try number conversion
                if re.fullmatch(r'-?\d+', value):
                    front[key] = int(value)
                elif re.fullmatch(r'-?\d+\.\d+', value):
                    front[key] = float(value)
                elif value.lower() in ('true', 'false'):
                    front[key] = value.lower() == 'true'
                else:
                    front[key] = value.strip('"').strip("'")

    return front, body.strip()


# ─────────────────────────────────────────────────────────────
#  LEVEL 1 — THE CATALOGUE (cheap, used by the orchestrator to plan)
# ─────────────────────────────────────────────────────────────

def get_agent_catalogue() -> List[Dict]:
    """
    Returns [{name, display_name, description, layer}] for every agent
    in the registry. Only reads frontmatter — does NOT load full skill
    bodies. This is Level-1 progressive disclosure.
    """
    catalogue = []
    if not os.path.isdir(REGISTRY_DIR):
        return catalogue

    for folder in sorted(os.listdir(REGISTRY_DIR)):
        agent_md = os.path.join(REGISTRY_DIR, folder, "AGENT.md")
        if not os.path.isfile(agent_md):
            continue
        try:
            with open(agent_md, "r", encoding="utf-8") as f:
                front, _ = _parse_frontmatter(f.read())
            catalogue.append({
                "name":         front.get("name", folder),
                "display_name": front.get("display_name", folder),
                "description":  front.get("description", ""),
                "layer":        front.get("layer", 1),
                "temperature":  front.get("temperature", 0.3),
            })
        except Exception as e:
            logger.warning(f"Could not read {agent_md}: {e}")
    return catalogue


# ─────────────────────────────────────────────────────────────
#  LEVEL 2 — FULL AGENT DEFINITION (loaded only when the agent runs)
# ─────────────────────────────────────────────────────────────

def load_agent(name: str) -> Optional[Dict]:
    """
    Loads the COMPLETE definition for one agent:
      - AGENT.md frontmatter (temperature, output_fields, layer...)
      - AGENT.md body        (the role description = start of system prompt)
      - SKILL.md body        (the workflow instructions = rest of system prompt)
    Returns None if the agent doesn't exist.
    """
    folder = os.path.join(REGISTRY_DIR, name)
    agent_md_path = os.path.join(folder, "AGENT.md")
    skill_md_path = os.path.join(folder, "SKILL.md")

    if not os.path.isfile(agent_md_path):
        return None

    with open(agent_md_path, "r", encoding="utf-8") as f:
        front, agent_body = _parse_frontmatter(f.read())

    skill_body = ""
    if os.path.isfile(skill_md_path):
        with open(skill_md_path, "r", encoding="utf-8") as f:
            _, skill_body = _parse_frontmatter(f.read())

    return {
        "name":          front.get("name", name),
        "display_name":  front.get("display_name", name),
        "description":   front.get("description", ""),
        "temperature":   float(front.get("temperature", 0.3)),
        "layer":         int(front.get("layer", 1)),
        "output_fields": front.get("output_fields", []),
        "agent_body":    agent_body,     # WHO the agent is
        "skill_body":    skill_body,     # HOW it does the job
    }


# ─────────────────────────────────────────────────────────────
#  RUNTIME AGENT CREATION (sir's requirement: user creates agents live)
# ─────────────────────────────────────────────────────────────

def create_agent_at_runtime(
    name: str,
    display_name: str,
    description: str,
    temperature: float,
    layer: int,
    output_fields: List[Dict],   # [{"name":"x","type":"str","description":"..."}]
    role_text: str,              # AGENT.md body
    skill_text: str,             # SKILL.md body
) -> Dict:
    """
    Creates a brand-new agent WHILE THE SERVER IS RUNNING.
    Writes AGENT.md + SKILL.md into agents_registry/{name}/ and records
    it in the custom_agents DB table. The agent becomes available to the
    orchestrator on the very next request — no restart, no code change.
    """
    if not re.fullmatch(r'[a-z0-9_]+', name):
        raise ValueError("Agent name must be lowercase letters, numbers, underscores only.")

    folder = os.path.join(REGISTRY_DIR, name)
    if os.path.isdir(folder) and os.path.isfile(os.path.join(folder, "AGENT.md")):
        raise ValueError(f"Agent '{name}' already exists.")

    os.makedirs(folder, exist_ok=True)

    # Build AGENT.md
    fields_yaml = "\n".join(
        f'  - {{name: {f["name"]}, type: {f.get("type","str")}, description: "{f.get("description","")}"}}'
        for f in output_fields
    )
    agent_md = f"""---
name: {name}
display_name: {display_name}
description: {description}
temperature: {temperature}
layer: {layer}
output_fields:
{fields_yaml}
---
{role_text}
"""
    with open(os.path.join(folder, "AGENT.md"), "w", encoding="utf-8") as f:
        f.write(agent_md)

    # Build SKILL.md
    skill_md = f"""---
name: {name}-skill
description: Workflow instructions for the {display_name}
---
{skill_text}
"""
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_md)

    # Record in database so it can be listed/managed via API
    try:
        from src.utils.db import get_db_connection
        from datetime import datetime, timezone
        with get_db_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS custom_agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    display_name TEXT,
                    description TEXT,
                    created_at TEXT
                )''')
            conn.execute(
                "INSERT OR REPLACE INTO custom_agents (name, display_name, description, created_at) VALUES (?,?,?,?)",
                (name, display_name, description, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"DB record for custom agent failed (files still created): {e}")

    return load_agent(name)


def delete_agent(name: str) -> bool:
    """Removes a runtime-created agent (files + DB row)."""
    import shutil
    folder = os.path.join(REGISTRY_DIR, name)
    existed = os.path.isdir(folder)
    if existed:
        shutil.rmtree(folder)
    try:
        from src.utils.db import get_db_connection
        with get_db_connection() as conn:
            conn.execute("DELETE FROM custom_agents WHERE name=?", (name,))
            conn.commit()
    except Exception:
        pass
    return existed