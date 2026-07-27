"""
routes_agents.py  — add to your main FastAPI app with:
    app.include_router(agent_router)

Endpoints:
  POST /agents/preview-url     — fetch GitHub URL, return pre-fill form data
  POST /agents/preview-file    — parse uploaded .md/.txt, return pre-fill form data
  POST /agents/create          — save confirmed agent to agents_registry/
  GET  /agents/list            — list all agents
  DELETE /agents/{slug}        — delete agent

  POST /config/set-endpoint    — save user's LLM endpoint (optional, only if clicked)
  GET  /config/get-endpoint    — return current endpoint config
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import os, json
from pathlib import Path

from agent_registry_manager import (
    fetch_github_url,
    parse_markdown_to_agent,
    save_agent,
    list_agents,
    delete_agent,
)

agent_router = APIRouter()

CONFIG_FILE = Path("llm_config.json")


# ── Models ─────────────────────────────────────────────────────────────────────

class AgentCreateRequest(BaseModel):
    name: str
    display_name: str
    description: str
    capabilities: str
    output_format: str
    extra_instructions: Optional[str] = ""
    raw_md: Optional[str] = ""


class GitHubURLRequest(BaseModel):
    url: str


class LLMEndpointConfig(BaseModel):
    api_base: str           # e.g. https://api.openai.com/v1
    api_key: str            # stored locally only
    model: str              # e.g. gpt-4o, gemini-1.5-pro
    provider: Optional[str] = "openai"  # openai | gemini | azure | ollama


# ── Agent routes ───────────────────────────────────────────────────────────────

@agent_router.post("/agents/preview-url")
async def preview_from_github(req: GitHubURLRequest):
    """Fetch a GitHub raw URL and return parsed agent fields for pre-fill."""
    try:
        md_text = await fetch_github_url(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {e}")
    parsed = parse_markdown_to_agent(md_text)
    return JSONResponse(parsed)


@agent_router.post("/agents/preview-file")
async def preview_from_file(file: UploadFile = File(...)):
    """Parse uploaded .md / .txt file and return pre-fill form data."""
    if not file.filename.endswith((".md", ".txt")):
        raise HTTPException(status_code=400, detail="Only .md or .txt files accepted")
    content = await file.read()
    try:
        md_text = content.decode("utf-8")
    except UnicodeDecodeError:
        md_text = content.decode("latin-1")
    parsed = parse_markdown_to_agent(md_text, fallback_name=file.filename.replace(".md","").replace(".txt",""))
    return JSONResponse(parsed)


@agent_router.post("/agents/create")
async def create_agent(req: AgentCreateRequest):
    """Save confirmed agent definition to agents_registry/."""
    try:
        path = save_agent(
            name=req.name,
            display_name=req.display_name,
            description=req.description,
            capabilities=req.capabilities,
            output_format=req.output_format,
            raw_md=req.raw_md or "",
            extra_instructions=req.extra_instructions or "",
        )
        return {"success": True, "file": path.name, "slug": path.stem}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@agent_router.get("/agents/list")
async def get_agents():
    return {"agents": list_agents()}


@agent_router.delete("/agents/{slug}")
async def remove_agent(slug: str):
    ok = delete_agent(slug)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"success": True}


# ── LLM config routes (optional — only if user clicks 'Choose Model') ──────────

@agent_router.post("/config/set-endpoint")
async def set_endpoint(cfg: LLMEndpointConfig):
    """
    Store user's LLM endpoint config locally.
    Also sets env vars so LiteLLM picks them up immediately.
    """
    data = cfg.dict()
    CONFIG_FILE.write_text(json.dumps(data, indent=2))

    # Set env vars for LiteLLM convention
    os.environ["OPENAI_API_BASE"] = cfg.api_base
    os.environ["OPENAI_API_KEY"] = cfg.api_key
    os.environ["LITELLM_MODEL"] = cfg.model

    return {"success": True, "model": cfg.model, "api_base": cfg.api_base}


@agent_router.get("/config/get-endpoint")
async def get_endpoint():
    """Return current LLM config (key redacted)."""
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
        data["api_key"] = "***redacted***"
        return data
    # Defaults from environment
    return {
        "api_base": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "model": os.environ.get("LITELLM_MODEL", "gpt-4o"),
        "provider": "openai",
        "api_key": "***redacted***",
        "source": "env_default"
    }