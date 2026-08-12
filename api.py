"""
api.py  — LandIQ v3
"""

import os
import time
import logging
import asyncio
import httpx
import json as _json
from contextlib import asynccontextmanager
from typing import Optional, List
from collections import defaultdict
from pathlib import Path as _Path

from fastapi import FastAPI, HTTPException, Request, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)


# ── EXTERNAL BASE URL HELPER ────────────────────────────────────────────────

def _get_ext_base() -> str:
    cfg_file = _Path("configs/external_active.json")
    if cfg_file.exists():
        try:
            data = _json.loads(cfg_file.read_text())
            base = data.get("external_base", "").strip().rstrip("/")
            if base:
                return base
        except Exception:
            pass
    env_base = os.environ.get("EXTERNAL_LLM_BASE", "").strip().rstrip("/")
    if env_base:
        return env_base
    return ""

_EXT_HEADERS = {
    "Accept": "application/json",
    "X-Tunnel-Skip-Auth-Redirect": "true",
    "ngrok-skip-browser-warning": "true",
}


# ── LIFESPAN ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from src.utils.db import init_db
        init_db()
    except Exception as e:
        logger.warning(f"  [DB] Init failed: {e}")
    # Load API keys from DB and inject into environment if not set
    try:
        from src.utils.db import get_db_connection
        with get_db_connection() as conn:
            for row in conn.execute("SELECT litellm_model, api_key, provider FROM global_models").fetchall():
                model_name = row["litellm_model"]
                key = row["api_key"]
                provider = row["provider"]
                if key:
                    if provider == "groq" and "GROQ_API_KEY" not in os.environ:
                        os.environ["GROQ_API_KEY"] = key
                        logger.info("  [DB Startup] Loaded GROQ_API_KEY from database")
                    elif provider in ("google", "gemini") and "GOOGLE_API_KEY" not in os.environ:
                        os.environ["GOOGLE_API_KEY"] = key
                        logger.info("  [DB Startup] Loaded GOOGLE_API_KEY from database")
                    elif provider == "openai" and "OPENAI_API_KEY" not in os.environ:
                        os.environ["OPENAI_API_KEY"] = key
                    elif provider == "anthropic" and "ANTHROPIC_API_KEY" not in os.environ:
                        os.environ["ANTHROPIC_API_KEY"] = key
    except Exception as e:
        logger.warning(f"  [DB] Injecting API keys failed: {e}")
    try:
        from src.utils.router_manager import load_all_configs_on_startup
        configs_dir = os.path.join(os.path.dirname(__file__), "configs")
        load_all_configs_on_startup(configs_dir)
    except Exception as e:
        logger.warning(f"  [ROUTER] Startup load failed: {e}")
    yield


app = FastAPI(title="LandIQ API", version="3.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ── AGENT REGISTRY IMPORTS ─────────────────────────────────────────────────

from src.utils.agent_registry_manager import (
    fetch_github_url,
    parse_markdown_to_agent,
    save_agent,
    list_agents as _list_registry_agents,
    delete_agent as _delete_agent_file,
    _slugify,
)
from src.utils.compression_utils import apply_compression
from src.utils.headroom_bridge import headroom_ctx, get_stats as get_headroom_stats, is_available as headroom_available, test_compression as headroom_test_compression


# ── RATE LIMITER ───────────────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self):
        self.windows: dict = defaultdict(list)
        self._lock = None

    def _get_lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def check(self, key: str, rpm_limit: int) -> bool:
        async with self._get_lock():
            now = time.time()
            self.windows[key] = [t for t in self.windows[key] if now - t < 60]
            if len(self.windows[key]) >= rpm_limit:
                return False
            self.windows[key].append(now)
            return True

    async def usage(self, key: str) -> dict:
        async with self._get_lock():
            now = time.time()
            self.windows[key] = [t for t in self.windows[key] if now - t < 60]
            return {"current_rpm": len(self.windows[key]), "window_seconds": 60}

_rate_limiter = _RateLimiter()


# ── SCHEMAS ────────────────────────────────────────────────────────────────

class LandQueryRequest(BaseModel):
    state: str
    city: str
    area: str
    pincode: Optional[str] = ""
    land_size: float
    land_unit: str
    land_type: str
    has_title_deed: bool
    total_budget: float
    construction_budget: Optional[float] = 0
    taking_loan: Optional[bool] = False
    loan_amount: Optional[float] = 0
    loan_interest_rate: Optional[float] = 0
    purpose: str
    timeline_years: int
    monthly_income_expectation: Optional[float] = 0
    risk_tolerance: str
    selected_agents: Optional[List[str]] = ["all"]
    caveman_mode: Optional[bool] = False
    caveman_level: Optional[str] = "full"
    selected_config: Optional[str] = None
    guardrail_mode: Optional[str] = "none"
    guardrail_config: Optional[dict] = None
    headroom_mode: bool = False
    skip_langflow: bool = False

    @field_validator("pincode", mode="before")
    @classmethod
    def _pincode_as_str(cls, v):
        # A JSON-body pincode like "560066" can arrive as an int when it passes
        # through a caller that auto-coerces numeric-looking strings (e.g. the
        # Langflow API Request node's body processing).
        return str(v) if v is not None else v


class GlobalModelCreate(BaseModel):
    litellm_model: str
    provider: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None


class CreateConfigRequest(BaseModel):
    usecase_name: str
    config_name: str
    operations: dict
    restrictions: dict
    guardrails: dict
    custom_operations: Optional[dict] = None


class UpdateConfigRequest(BaseModel):
    operations: Optional[dict] = None
    restrictions: Optional[dict] = None
    guardrails: Optional[dict] = None


class TestBoardRequest(BaseModel):
    prompt: str = "Say hello and state your model name."
    max_tokens: int = 100
    temperature: float = 0.3


class OutputFieldDef(BaseModel):
    name: str
    type: str = "str"
    description: str = ""


class CreateAgentRequest(BaseModel):
    name: str
    display_name: str
    description: str
    temperature: float = 0.3
    layer: int = 1
    output_fields: List[OutputFieldDef]
    role_text: str
    skill_text: str


class ExternalGetRequest(BaseModel):
    url: str

class ExternalPostRequest(BaseModel):
    url: str
    body: dict = {}

class SetExternalConfigRequest(BaseModel):
    external_base: str
    config_name: str
    chat_endpoint: str

class SetExternalBaseRequest(BaseModel):
    external_base: str

class GuardrailAPITestRequest(BaseModel):
    endpoint_url: str
    api_key: Optional[str] = ""
    test_prompt: str = "Is this land investment safe?"

class GuardrailHFTestRequest(BaseModel):
    model_or_url: str
    hf_token: Optional[str] = ""

class LocalGuardrailRequest(BaseModel):
    text: str
    pii_enabled: bool = True
    pii_action: str = "MASK"
    safety_enabled: bool = True
    topic_check: bool = False


# ── SERVE PAGES ─────────────────────────────────────────────────────────────

@app.get("/")
def serve_frontend():
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return JSONResponse({"message": "LandIQ API running. Docs at /docs"})

@app.get("/configure-models.html")
def serve_configure_models():
    return FileResponse("frontend/configure-models.html")

@app.get("/create-configuration.html")
def serve_create_configuration():
    return FileResponse("frontend/create-configuration.html")

@app.get("/llm-setup.html")
def serve_llm_setup():
    return FileResponse("frontend/llm-setup.html")

@app.get("/configurator.html")
def serve_configurator():
    return FileResponse("frontend/llm-setup.html")

@app.get("/external-onboarding.html")
def serve_external_onboarding():
    return FileResponse("frontend/external_onboarding.html")

@app.get("/health")
def health_check():
    try:
        from src.utils.config_store import list_configs
        active = [c for c in list_configs() if c["status"] == "active"]
    except Exception:
        active = []
    return {
        "status": "healthy", "version": "3.1.0",
        "active_configurations": len(active),
        "configurations": [c["full_name"] for c in active],
        "external_base": _get_ext_base(),
    }


# ── AGENT REGISTRY ENDPOINTS ───────────────────────────────────────────────

@app.post("/agents/preview-url")
async def preview_agent_from_url(request: Request):
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    try:
        md_text = await fetch_github_url(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fetch failed: {e}")
    return parse_markdown_to_agent(md_text)

@app.post("/agents/preview-file")
async def preview_agent_from_file(file: UploadFile = File(...)):
    if not file.filename.endswith((".md", ".txt")):
        raise HTTPException(status_code=400, detail="Only .md or .txt")
    content = await file.read()
    try:
        md_text = content.decode("utf-8")
    except Exception:
        md_text = content.decode("latin-1")
    return parse_markdown_to_agent(
        md_text,
        fallback_name=file.filename.replace(".md", "").replace(".txt", "")
    )

@app.post("/agents/create")
async def create_agent_registry(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    display_name = body.get("display_name", "").strip()
    if not name or not display_name:
        raise HTTPException(status_code=400, detail="name and display_name required")
    folder = save_agent(
        name=name,
        display_name=display_name,
        description=body.get("description", ""),
        capabilities=body.get("capabilities", ""),
        output_format=body.get("output_format", ""),
        raw_md=body.get("raw_md", ""),
        extra_instructions=body.get("extra_instructions", ""),
    )
    return {"success": True, "file": folder.name, "slug": folder.name}

@app.get("/agents/list")
async def list_registry_agents():
    return {"agents": _list_registry_agents()}

@app.post("/compress/stats")
async def compression_stats(request: Request):
    body = await request.json()
    result = apply_compression(
        body.get("text", ""),
        use_caveman=body.get("use_caveman", False),
        caveman_mode=body.get("caveman_mode", "lite"),
        use_toon=body.get("use_toon", False),
    )
    return result

_LLM_CONFIG_FILE = _Path("configs/llm_endpoint.json")

@app.post("/config/set-endpoint")
async def set_llm_endpoint(request: Request):
    body = await request.json()
    _LLM_CONFIG_FILE.parent.mkdir(exist_ok=True)
    _LLM_CONFIG_FILE.write_text(_json.dumps(body, indent=2))
    os.environ["OPENAI_API_BASE"] = body.get("api_base", "")
    os.environ["OPENAI_API_KEY"] = body.get("api_key", "")
    os.environ["LITELLM_MODEL"] = body.get("model", "")
    return {"success": True, "model": body.get("model")}

@app.get("/config/get-endpoint")
async def get_llm_endpoint():
    if _LLM_CONFIG_FILE.exists():
        data = _json.loads(_LLM_CONFIG_FILE.read_text())
        data["api_key"] = "***"
        return data
    return {
        "api_base": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "model": os.environ.get("LITELLM_MODEL", "gpt-4o"),
        "source": "env_default",
    }


# ── CATALOGUE ──────────────────────────────────────────────────────────────

@app.get("/catalog/models")
def catalog_models(provider: Optional[str] = None, q: Optional[str] = None, limit: int = 500):
    try:
        from src.utils.catalog import get_all_chat_models
        models = get_all_chat_models(provider_filter=provider, query=q, limit=limit)
        return {"models": models, "total": len(models)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/catalog/providers")
def catalog_providers():
    try:
        from src.utils.catalog import get_unique_providers
        return {"providers": get_unique_providers()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/catalog/global_models")
def list_pool_models():
    try:
        from src.utils.db import get_global_models
        models = get_global_models()
        for m in models:
            m["has_api_key"] = bool(m.get("api_key"))
            m.pop("api_key", None)
        return models
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/catalog/global_models", status_code=201)
def add_pool_model(req: GlobalModelCreate):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="api_key is required.")
    try:
        from src.utils.db import add_global_model
        add_global_model(req.litellm_model, req.provider, req.api_key, req.api_base)
        return {"status": "added", "litellm_model": req.litellm_model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/catalog/global_models/{litellm_model:path}")
def remove_pool_model(litellm_model: str):
    try:
        from src.utils.db import delete_global_model
        delete_global_model(litellm_model)
        return {"status": "removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── LLM CONFIGURATIONS ─────────────────────────────────────────────────────

@app.get("/configs")
def list_all_configs():
    try:
        from src.utils.config_store import list_configs
        return list_configs()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/configs/active")
def list_active_configs():
    try:
        from src.utils.config_store import list_configs
        return [c for c in list_configs() if c["status"] == "active"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/configs", status_code=201)
def create_config(req: CreateConfigRequest):
    try:
        from src.utils.schemas import ConfigRequest as V
        validated = V(**req.model_dump())
    except ValidationError as e:
        clean = [f"{' -> '.join(str(x) for x in err.get('loc',[]))}: {err.get('msg')}" for err in e.errors()]
        raise HTTPException(status_code=422, detail=clean)
    try:
        from src.utils.config_store import create_config as _create
        from src.utils.router_manager import build_router_for_config, get_capabilities
        record = _create(validated.model_dump())
        build_router_for_config(record)
        try:
            caps = get_capabilities(record["full_name"])
        except Exception:
            caps = {}
        return {"config": record, "capabilities": caps}
    except Exception as e:
        raise HTTPException(status_code=409 if "already exists" in str(e).lower() else 400, detail=str(e))

@app.get("/configs/{full_name}")
def get_config(full_name: str):
    try:
        from src.utils.config_store import get_config as _get
        cfg = _get(full_name)
        if not cfg:
            raise HTTPException(status_code=404, detail="Config not found")
        return cfg
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/configs/{full_name}", status_code=204)
def delete_config(full_name: str):
    try:
        from src.utils.config_store import delete_config as _del
        from src.utils.router_manager import evict_router
        if not _del(full_name):
            raise HTTPException(status_code=404, detail="Config not found")
        evict_router(full_name)
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/configs/{full_name}/enable")
def enable_config(full_name: str):
    try:
        from src.utils.config_store import update_config_status, get_config as _get
        from src.utils.router_manager import build_router_for_config
        update_config_status(full_name, "active")
        cfg = _get(full_name)
        if cfg:
            build_router_for_config(cfg)
        return {"status": "active", "full_name": full_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/configs/{full_name}/disable")
def disable_config(full_name: str):
    try:
        from src.utils.config_store import update_config_status
        from src.utils.router_manager import evict_router
        update_config_status(full_name, "disabled")
        evict_router(full_name)
        return {"status": "disabled", "full_name": full_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/configs/{full_name}")
def edit_config(full_name: str, req: UpdateConfigRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    try:
        from src.utils.config_store import update_config
        from src.utils.router_manager import build_router_for_config, evict_router
        record = update_config(full_name, updates)
        evict_router(full_name)
        build_router_for_config(record)
        return {"status": "updated", "config": record}
    except Exception as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 500, detail=str(e))


# ── TEST BOARD ─────────────────────────────────────────────────────────────

@app.post("/test/{full_name}")
async def test_board(full_name: str, req: TestBoardRequest):
    from src.utils.router_manager import get_router, _configs
    from src.utils.db import log_usage
    from datetime import datetime, timezone
    cfg = _configs.get(full_name)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Config '{full_name}' not active.")
    router = get_router(full_name)
    if not router:
        raise HTTPException(status_code=404, detail=f"No router for '{full_name}'.")
    start_dt = datetime.now(timezone.utc)
    start_ts = time.time()
    try:
        resp = await router.acompletion(
            model=f"{full_name}::chat",
            messages=[{"role": "user", "content": req.prompt}],
            max_tokens=req.max_tokens, temperature=req.temperature,
        )
        latency_ms = (time.time() - start_ts) * 1000
        model_used = getattr(resp, "model", "unknown")
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        tt = getattr(usage, "total_tokens", 0) or 0
        text = resp.choices[0].message.content if resp.choices else ""
        cost = tt * 0.000001
        end_dt = datetime.now(timezone.utc)
        log_usage(full_name, "test_board", "/test", model_used, pt, ct, tt, latency_ms, True, None,
                  cost_usd=cost, start_time=start_dt.isoformat(), end_time=end_dt.isoformat())
        return {"success": True, "model_used": model_used, "response": text,
                "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt,
                "latency_ms": round(latency_ms, 1), "estimated_cost_usd": round(cost, 6)}
    except Exception as e:
        latency_ms = (time.time() - start_ts) * 1000
        end_dt = datetime.now(timezone.utc)
        log_usage(full_name, "test_board", "/test", None, 0, 0, 0, latency_ms, False, str(e),
                  start_time=start_dt.isoformat(), end_time=end_dt.isoformat())
        raise HTTPException(status_code=502, detail=f"Test failed: {str(e)}")


# ── REQUEST LOGS ───────────────────────────────────────────────────────────

@app.get("/logs")
def get_all_logs(limit: int = 100):
    try:
        from src.utils.db import get_request_logs
        logs = get_request_logs(config_full_name=None, limit=limit)
        return {"logs": logs, "total": len(logs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/logs/{full_name}")
def get_config_logs(full_name: str, limit: int = 100):
    try:
        from src.utils.db import get_request_logs
        logs = get_request_logs(config_full_name=full_name, limit=limit)
        return {"config": full_name, "logs": logs, "total": len(logs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── DYNAMIC AGENTS (agent_loader) ──────────────────────────────────────────

@app.get("/agents")
def list_agents():
    try:
        from src.utils.agent_loader import get_agent_catalogue
        return {"agents": get_agent_catalogue()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agents/{name}")
def get_agent_def(name: str):
    try:
        from src.utils.agent_loader import load_agent
        agent = load_agent(name)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return agent
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agents", status_code=201)
def create_agent_loader(req: CreateAgentRequest):
    try:
        from src.utils.agent_loader import create_agent_at_runtime
        from src.agents.dynamic_agent import clear_model_cache
        agent = create_agent_at_runtime(
            name=req.name, display_name=req.display_name,
            description=req.description, temperature=req.temperature,
            layer=req.layer, output_fields=[f.model_dump() for f in req.output_fields],
            role_text=req.role_text, skill_text=req.skill_text,
        )
        clear_model_cache(req.name)
        return {"status": "created", "agent": agent}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/agents/{name}", status_code=204)
def remove_agent_endpoint(name: str):
    PROTECTED = {"location","legal","financial","market","bull","bear","due_diligence","senior_consultant"}
    if name in PROTECTED:
        raise HTTPException(status_code=403, detail=f"'{name}' is a core agent and cannot be deleted.")
    try:
        from src.utils.agent_loader import delete_agent
        from src.agents.dynamic_agent import clear_model_cache
        if not delete_agent(name):
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        clear_model_cache(name)
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── LLM PROXY ──────────────────────────────────────────────────────────────

async def _llm_pre_flight(full_name: str, body: dict) -> dict:
    from src.utils.router_manager import _configs
    cfg = _configs.get(full_name)
    if not cfg or cfg.get("status") != "active":
        raise HTTPException(status_code=404, detail=f"Config '{full_name}' not found or disabled.")
    rpm = cfg.get("restrictions", {}).get("rpm", 60)
    if not await _rate_limiter.check(full_name, rpm):
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded -- max {rpm} RPM.")
    tpr = cfg.get("restrictions", {}).get("tpr", 4096)
    if body.get("max_tokens") is None:
        body["max_tokens"] = tpr
    elif body["max_tokens"] > tpr:
        raise HTTPException(status_code=400, detail=f"max_tokens exceeds config cap of {tpr}.")
    return cfg

async def _exec_router_call(full_name, endpoint, agent_id, coro):
    from src.utils.db import log_usage
    from datetime import datetime, timezone
    start_dt = datetime.now(timezone.utc)
    start = time.time()
    try:
        resp = await coro
        ms = (time.time() - start) * 1000
        model_used = getattr(resp, "model", None)
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        tt = getattr(usage, "total_tokens", 0) or 0
        cost = tt * 0.000001
        end_dt = datetime.now(timezone.utc)
        log_usage(full_name, agent_id, endpoint, model_used, pt, ct, tt, ms, True, None,
                  cost_usd=cost, start_time=start_dt.isoformat(), end_time=end_dt.isoformat())
        d = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        d["model_used"] = model_used
        return JSONResponse(content=d)
    except Exception as e:
        ms = (time.time() - start) * 1000
        end_dt = datetime.now(timezone.utc)
        log_usage(full_name, agent_id, endpoint, None, 0, 0, 0, ms, False, str(e),
                  start_time=start_dt.isoformat(), end_time=end_dt.isoformat())
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/llm/{full_name}/chat")
async def llm_chat(full_name: str, request: Request, x_agent_id: Optional[str] = Header(None)):
    from src.utils.router_manager import get_router
    body = await request.json()
    await _llm_pre_flight(full_name, body)
    router = get_router(full_name)
    if not router:
        raise HTTPException(status_code=404, detail=f"No router built for '{full_name}'.")
    coro = router.acompletion(model=f"{full_name}::chat", **body)
    return await _exec_router_call(full_name, "/chat", x_agent_id, coro)

@app.get("/llm/{full_name}/usage")
async def llm_usage(full_name: str):
    try:
        from src.utils.db import get_usage_stats
        stats = get_usage_stats(full_name)
        stats["rate_window"] = await _rate_limiter.usage(full_name)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/llm/{full_name}/capabilities")
def llm_capabilities(full_name: str):
    try:
        from src.utils.router_manager import get_capabilities
        return get_capabilities(full_name)
    except ValueError:
        raise HTTPException(status_code=404, detail="Config not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── CAVEMAN ────────────────────────────────────────────────────────────────

@app.post("/caveman")
def toggle_caveman(active: bool, level: str = "full"):
    from src.utils.caveman_mode import set_caveman, is_active, get_level
    set_caveman(active, level)
    return {"caveman_mode": is_active(), "caveman_level": get_level()}


# ── EXTERNAL SERVER PROXY ─────────────────────────────────────────────────

@app.post("/external-proxy/get")
async def external_proxy_get(req: ExternalGetRequest):
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(req.url, headers=_EXT_HEADERS)
        ct = r.headers.get("content-type","")
        if "html" in ct:
            return {"success": False, "status": r.status_code, "data": [], "error": "TUNNEL_AUTH"}
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        return {"success": r.status_code < 400, "status": r.status_code, "data": data}
    except Exception as e:
        return {"success": False, "status": 0, "data": [], "error": str(e)}

@app.post("/external-proxy/post")
async def external_proxy_post(req: ExternalPostRequest):
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            r = await client.post(req.url, json=req.body, headers=_EXT_HEADERS)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        return {"success": r.status_code < 400, "status": r.status_code, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/config/set-external")
async def set_external_config(req: SetExternalConfigRequest):
    cfg_file = _Path("configs/external_active.json")
    cfg_file.parent.mkdir(exist_ok=True)
    cfg_file.write_text(_json.dumps({
        "external_base": req.external_base.strip().rstrip("/"),
        "config_name": req.config_name,
        "chat_endpoint": req.chat_endpoint,
        "active": True
    }, indent=2))
    os.environ["EXTERNAL_LLM_BASE"] = req.external_base.strip().rstrip("/")
    os.environ["EXTERNAL_CONFIG_NAME"] = req.config_name
    return {"success": True, "message": f"External config '{req.config_name}' set as active."}

@app.get("/config/get-external")
async def get_external_config():
    cfg_file = _Path("configs/external_active.json")
    if cfg_file.exists():
        data = _json.loads(cfg_file.read_text())
        data["current_base"] = _get_ext_base()
        return data
    return {"external_base": _get_ext_base(), "current_base": _get_ext_base(),
            "config_name": os.environ.get("EXTERNAL_CONFIG_NAME", ""), "active": False}

@app.post("/external/set-base")
async def set_external_base(req: SetExternalBaseRequest):
    new_base = req.external_base.strip().rstrip("/")
    cfg_file = _Path("configs/external_active.json")
    cfg_file.parent.mkdir(exist_ok=True)
    existing = {}
    if cfg_file.exists():
        try:
            existing = _json.loads(cfg_file.read_text())
        except Exception:
            pass
    existing["external_base"] = new_base
    existing["active"] = True
    cfg_file.write_text(_json.dumps(existing, indent=2))
    os.environ["EXTERNAL_LLM_BASE"] = new_base
    return {"success": True, "external_base": new_base}

@app.get("/external/base-url")
async def get_external_base():
    return {"external_base": _get_ext_base()}

@app.get("/external/configs")
async def list_external_configs_proxy():
    ext_base = _get_ext_base()
    if not ext_base:
        return {"configs": [], "error": "NO_URL", "message": "Paste the student server URL in the Server URL box above", "external_base": ""}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(f"{ext_base}/configs", headers=_EXT_HEADERS)
        content_type = r.headers.get("content-type", "")
        if "html" in content_type:
            return {"configs": [], "error": "DEVTUNNEL_AUTH",
                    "message": "Set Port Visibility to Public in VS Code PORTS tab", "external_base": ext_base}
        raw = r.text
        if not raw or not raw.strip():
            return {"configs": [], "error": "EMPTY_RESPONSE",
                    "message": f"Student server returned empty response. Status: {r.status_code}", "external_base": ext_base}
        try:
            data = r.json()
        except Exception as je:
            return {"configs": [], "error": "PARSE_ERROR",
                    "message": f"Could not parse response: {raw[:200]}", "external_base": ext_base}

        # Handle all possible response shapes
        if isinstance(data, list):
            configs = data
        elif isinstance(data, dict):
            # Try every common key name
            configs = (data.get("configs") or data.get("items") or
                       data.get("data") or data.get("results") or [])
            if not isinstance(configs, list):
                # Maybe the dict itself is one config
                if data.get("full_name") or data.get("config_name") or data.get("name"):
                    configs = [data]
                else:
                    configs = []
        else:
            configs = []

        # Return ALL configs — don't filter by status, different servers use different values
        return {
            "source": ext_base,
            "configs": configs,
            "all_configs": configs,
            "count": len(configs),
            "raw_keys": list(data.keys()) if isinstance(data, dict) else "list"
        }
    except httpx.ConnectError:
        return {"configs": [], "error": "OFFLINE", "message": "Student server unreachable — check the URL", "external_base": ext_base}
    except httpx.TimeoutException:
        return {"configs": [], "error": "TIMEOUT", "message": "Student server timed out after 20s", "external_base": ext_base}
    except Exception as e:
        return {"configs": [], "error": str(e), "external_base": ext_base}


# ── GUARDRAILS ────────────────────────────────────────────────────────────

@app.post("/guardrails/test")
async def test_guardrail_api(req: GuardrailAPITestRequest):
    try:
        headers = {"Content-Type": "application/json"}
        if req.api_key:
            headers["Authorization"] = f"Bearer {req.api_key}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(req.endpoint_url, json={"text": req.test_prompt}, headers=headers)
        return {"success": resp.status_code < 400, "status_code": resp.status_code, "response": resp.text[:200]}
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot reach guardrail endpoint.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/guardrails/test-hf")
async def test_guardrail_hf(req: GuardrailHFTestRequest):
    import requests as _req
    model = req.model_or_url.strip()
    headers = {"Content-Type": "application/json"}
    if req.hf_token:
        headers["Authorization"] = f"Bearer {req.hf_token}"
    for url in [
        f"https://router.huggingface.co/hf-inference/models/{model}",
        f"https://api-inference.huggingface.co/models/{model}",
    ]:
        try:
            r = _req.post(url, json={"inputs": "Is land in Mumbai safe?"}, headers=headers, timeout=15)
            if r.status_code == 401:
                return {"success": False, "model": model, "response": "Invalid token"}
            if r.status_code in (200, 503):
                return {"success": True, "model": model, "url_used": url, "response": "Connected to " + model}
        except Exception:
            continue
    return {"success": False, "model": model, "response": "HuggingFace blocked by network. PII masking works locally."}

@app.post("/guardrails/run-local")
async def run_local_guardrail(request: Request):
    body = await request.json()
    config_path = body.get("config_path", "./guardrails/config")
    text = body.get("text", "")
    try:
        from nemoguardrails import RailsConfig, LLMRails
        config = RailsConfig.from_path(config_path)
        rails = LLMRails(config)
        response = await rails.generate_async(messages=[{"role": "user", "content": text}])
        return {"success": True, "output": response, "source": "local_nemo"}
    except ImportError:
        return {"success": False, "error": "Run: pip install nemoguardrails", "source": "local_nemo"}
    except Exception as e:
        return {"success": False, "error": str(e), "source": "local_nemo"}


# ── LOCAL DEBERTA GUARDRAIL (Student's Model) ─────────────────────────────

GUARDRAIL_SERVER = "http://localhost:8002"

@app.get("/guardrails/deberta/health")
async def deberta_health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{GUARDRAIL_SERVER}/health")
        return r.json()
    except httpx.ConnectError:
        return {"status": "offline", "message": "Start with: python guardrail_server.py"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/guardrails/deberta/run")
async def deberta_run(req: LocalGuardrailRequest):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{GUARDRAIL_SERVER}/run", json={
                "text": req.text,
                "pii_enabled": req.pii_enabled,
                "pii_action": req.pii_action,
                "safety_enabled": req.safety_enabled,
                "topic_check": req.topic_check,
            })
        return r.json()
    except httpx.ConnectError:
        return {"allowed": False, "processed_text": req.text, "pii_found": None,
                "blocked_reason": None, "error": "Guardrail server offline — run: python guardrail_server.py"}
    except Exception as e:
        return {"allowed": False, "processed_text": req.text, "pii_found": None,
                "blocked_reason": None, "error": f"Guardrail error: {str(e)}"}


# ── EXTERNAL CONFIG REGISTRATION ──────────────────────────────────────────

import threading
_ext_ctx = threading.local()

async def _try_register_external_config(config_name: str) -> bool:
    ext_base = _get_ext_base()
    if not ext_base:
        return False
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            r = await client.get(f"{ext_base}/configs/{config_name}", headers=_EXT_HEADERS)
        if "html" in r.headers.get("content-type", ""):
            logger.warning("[EXTERNAL] Tunnel auth wall")
            return False
        if r.status_code >= 400:
            return False
        data = r.json()
        if data.get("error"):
            return False
    except Exception as e:
        logger.warning(f"[EXTERNAL] Cannot reach {ext_base}: {repr(e)}")
        return False

    try:
        from src.utils.router_manager import _configs
        ops = data.get("operations", {})
        rst = data.get("restrictions", {})
        _configs[config_name] = {
            "full_name": config_name, "status": "active",
            "operations": ops, "restrictions": rst,
            "guardrails": data.get("guardrails", {}),
            "_external": True, "_external_base": ext_base,
        }
        logger.info(f"[EXTERNAL] Config '{config_name}' registered from {ext_base}")
        return True
    except Exception as e:
        logger.warning(f"[EXTERNAL] Registration failed: {repr(e)}")
        return False


# ── MAIN ANALYSE ───────────────────────────────────────────────────────────

import re
from typing import Any

def _mask_pii_local(text: str) -> str:
    patterns = {
        "AADHAAR":  r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b",
        "PAN":      r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        "PHONE":    r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b",
        "EMAIL":    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
        "PASSPORT": r"\b[A-Z][1-9]\d{7}\b",
        "VPA":      r"\b[\w.\-]+@[a-zA-Z]+\b",
        "ACCOUNT":  r"\b\d{9,18}\b",
        "IFSC":     r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    }
    processed = text
    for pii_type, pattern in patterns.items():
        processed = re.sub(pattern, f"[{pii_type} MASKED]", processed, flags=re.IGNORECASE)
    return processed

def _check_harmful_local(text: str) -> bool:
    harmful_patterns = [
        r"\b(bomb|explosive|grenade|weapon|terrorist|kill\s+\w+|attack\s+\w+)\b",
        r"\b(suicide|self.?harm|cut\s+myself|end\s+my\s+life)\b",
        r"\b(hack|sql\s*injection|xss|ddos|malware|ransomware|phishing)\b",
        r"\b(porn|adult\s+content|xxx|nude|sexual)\b",
        r"\b(drug|cocaine|heroin|meth|narcotics)\b",
        r"\b(money\s*launder|black\s*money|hawala|bribe)\b",
    ]
    text_lower = text.lower()
    for pattern in harmful_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False

def _apply_guardrails_to_obj(obj: Any, mode: str) -> Any:
    if mode == "none" or not mode:
        return obj
    if isinstance(obj, str):
        if _check_harmful_local(obj):
            return "[Blocked by safety guardrail]"
        return _mask_pii_local(obj)
    elif isinstance(obj, list):
        return [_apply_guardrails_to_obj(item, mode) for item in obj]
    elif isinstance(obj, dict):
        return {k: _apply_guardrails_to_obj(v, mode) for k, v in obj.items()}
    return obj

@app.post("/analyse")
async def analyse_land(req: LandQueryRequest):
    session_start = time.time()
    def _safe_dump(obj):
        if obj is None: return None
        if hasattr(obj,'model_dump'): return obj.model_dump()
        if isinstance(obj,dict): return obj
        return {'summary': str(obj)}
    from src.utils.caveman_mode import set_caveman, is_active, get_level
    from src.graph.orchestrator_agent import run_dynamic_advisor
    from src.utils.config_store import get_config as _get_cfg, list_configs

    if not req.selected_config:
        active = [c for c in list_configs() if c["status"] == "active"]
        if active:
            req.selected_config = active[0]["full_name"]
    else:
        local_cfg = _get_cfg(req.selected_config)
        if not local_cfg or local_cfg.get("status") != "active":
            from src.utils.router_manager import _configs as _rcfgs
            if req.selected_config not in _rcfgs:
                ok = await _try_register_external_config(req.selected_config)
                if not ok:
                    active = [c for c in list_configs() if c["status"] == "active"]
                    if active:
                        logger.warning(f"[ANALYSE] Falling back to '{active[0]['full_name']}'")
                        req.selected_config = active[0]["full_name"]
                    else:
                        raise HTTPException(status_code=400,
                            detail=f"Config '{req.selected_config}' not found. Go to /static/llm-setup.html to create one.")

    set_caveman(req.caveman_mode, req.caveman_level)
    user_inputs = req.model_dump()
    user_inputs["llm_config_full_name"] = req.selected_config

    from src.utils.llm_factory import (
        set_active_config,
        clear_active_config,
        set_active_external_config,
        clear_active_external_config
    )
    from src.utils.router_manager import _configs as _rcfgs

    cfg = _rcfgs.get(req.selected_config, {})
    if cfg.get("_external"):
        set_active_external_config(req.selected_config, cfg.get("_external_base"))
    else:
        set_active_config(req.selected_config)
    # Config is activated BEFORE the Langflow attempt below so that when the
    # Langflow "LandIQ Orchestrator" component calls back into
    # /run-single-agent for each agent, those calls use the same selected
    # LLM config as the rest of this request (not whatever was last active).

    final_state = None
    _headroom_stats = None

    try:
        # ── Langflow: try the visual pipeline first, fall back to local ─────
        # skip_langflow is set True only by /internal/run-full-pipeline when IT
        # calls back into this function, so Langflow can never trigger itself.
        if not req.skip_langflow:
            try:
                from src.utils.langflow_bridge import is_langflow_running, get_flow_id, run_langflow
                _lf_flow_id = get_flow_id()
                if is_langflow_running() and _lf_flow_id:
                    print(f"  [LANGFLOW] Attempting via flow {_lf_flow_id}...")
                    _lf_result = await run_langflow(_json.dumps(user_inputs), timeout=300)
                    _lf_parsed = None
                    if _lf_result and _lf_result.get("response"):
                        _lf_text = _lf_result["response"]
                        try:
                            _lf_parsed = _json.loads(_lf_text)
                        except Exception:
                            try:
                                import ast as _ast
                                _lf_parsed = _ast.literal_eval(_lf_text)
                            except Exception:
                                _lf_parsed = None
                        print(f"[LANGFLOW DEBUG] Raw response type: {type(_lf_parsed)}")
                        print(f"[LANGFLOW DEBUG] Raw response keys: {_lf_parsed.keys() if isinstance(_lf_parsed, dict) else 'not a dict'}")
                        print(f"[LANGFLOW DEBUG] Raw response (first 500 chars): {str(_lf_parsed)[:500]}")
                    # The "LandIQ Orchestrator" Langflow component (see
                    # src/langflow/orchestrator_component_v2.py) returns the
                    # SAME state-shaped dict run_dynamic_advisor() returns —
                    # location_output, completed_agents, execution_plan,
                    # total_time_seconds, orchestrator_source, etc — NOT the
                    # final /analyse response shape (it has no "success" or
                    # "recommendation" key). So it's used as a drop-in
                    # replacement for final_state and flows through the exact
                    # same assembly code below as the local path, instead of
                    # being returned directly.
                    if isinstance(_lf_parsed, dict) and _lf_parsed.get("completed_agents"):
                        final_state = _lf_parsed
                        final_state.setdefault("orchestrator_source", "langflow")
                        print(f"  [LANGFLOW] Success — {len(final_state.get('completed_agents', []))} agents completed")
                    else:
                        print("  [LANGFLOW] No usable structured result — falling back to local")
                else:
                    print("  [LANGFLOW] Not running or no flow configured — using local orchestrator")
            except Exception as e:
                print(f"  [LANGFLOW] Attempt failed ({str(e)[:120]}) — falling back to local")

        if final_state is None:
            # ── Headroom: compress input tokens if enabled ──
            _hm = user_inputs.get('headroom_mode', False)
            with headroom_ctx(_hm):
                final_state = run_dynamic_advisor(user_inputs)
            final_state.setdefault("orchestrator_source", "local")
            _headroom_stats = get_headroom_stats()
        else:
            _headroom_stats = {"enabled": False, "available": headroom_available()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
    finally:
        clear_active_config()
        clear_active_external_config()

    loc  = final_state.get("location_output")
    leg  = final_state.get("legal_output")
    fin  = final_state.get("financial_output")
    mkt  = final_state.get("market_output")
    bull = final_state.get("bull_output")
    bear = final_state.get("bear_output")
    dd   = final_state.get("due_diligence_output")
    rec  = final_state.get("final_recommendation")
    tokens = final_state.get("token_report", {})
    if not tokens:
        completed = final_state.get("completed_agents", [])
        tokens = {"total_llm_calls": len(completed)}

    CORE_OUTPUT_KEYS = {
        "location_output","legal_output","financial_output","market_output",
        "bull_output","bear_output","due_diligence_output",
        "final_recommendation","senior_consultant_output",
        "token_report","completed_agents","error_log","rag_context",
    }
    dynamic_outputs = {}
    for key, value in final_state.items():
        if key.endswith("_output") and key not in CORE_OUTPUT_KEYS and value is not None:
            agent_key = key[:-7]
            try:
                dynamic_outputs[agent_key] = (
                    value.model_dump() if hasattr(value, "model_dump")
                    else dict(value) if isinstance(value, dict)
                    else {"summary": str(value)}
                )
            except Exception:
                dynamic_outputs[agent_key] = {"summary": str(value)}

    # Convert Pydantic outputs to dicts before returning
    loc_d  = _safe_dump(loc)
    leg_d  = _safe_dump(leg)
    fin_d  = _safe_dump(fin)
    mkt_d  = _safe_dump(mkt)
    bull_d = _safe_dump(bull)
    bear_d = _safe_dump(bear)
    dd_d   = _safe_dump(dd)
    rec_d  = _safe_dump(rec)

    # Apply output guardrails if configured
    mode = req.guardrail_mode or "none"
    if mode != "none":
        loc_d  = _apply_guardrails_to_obj(loc_d, mode)
        leg_d  = _apply_guardrails_to_obj(leg_d, mode)
        fin_d  = _apply_guardrails_to_obj(fin_d, mode)
        mkt_d  = _apply_guardrails_to_obj(mkt_d, mode)
        bull_d = _apply_guardrails_to_obj(bull_d, mode)
        bear_d = _apply_guardrails_to_obj(bear_d, mode)
        dd_d   = _apply_guardrails_to_obj(dd_d, mode)
        rec_d  = _apply_guardrails_to_obj(rec_d, mode)
        dynamic_outputs = _apply_guardrails_to_obj(dynamic_outputs, mode)

    return {
        "success": True,
        "caveman_mode": is_active(), "caveman_level": get_level(),
        "llm_configuration": req.selected_config,
        "property_details": {
            "state": req.state, "city": req.city, "area": req.area,
            "land_size": req.land_size, "land_unit": req.land_unit,
            "land_type": req.land_type, "total_budget": req.total_budget,
            "purpose": req.purpose, "timeline_years": req.timeline_years,
        },
        "location":       loc_d,
        "legal":          leg_d,
        "financial":      fin_d,
        "market":         mkt_d,
        "bull_case":      bull_d,
        "bear_case":      bear_d,
        "due_diligence":  dd_d,
        "recommendation": rec_d,
        "completed_agents": final_state.get("completed_agents", []),
        "errors":           final_state.get("error_log", []),
        "token_report":     tokens,
        "headroom_report":  _headroom_stats,
        "headroom_stats":   final_state.get("headroom_stats"),
        "caveman_stats":    final_state.get("caveman_stats"),
        "execution_plan":   final_state.get("execution_plan"),
        "orchestrator_source": final_state.get("orchestrator_source", "local"),
        "dynamic_agents":   dynamic_outputs,
        "orch_plan":        final_state.get("_orch_plan", None),
        "timing": {
            "total_seconds": round(time.time() - session_start, 2),
            "start_time": time.strftime("%H:%M:%S", time.localtime(session_start)),
            "end_time": time.strftime("%H:%M:%S", time.localtime()),
        },
        "total_time_seconds": final_state.get("total_time_seconds"),
        "mlflow_logged":    final_state.get("mlflow_logged", False),
    }


# ── CHAT PROXY ────────────────────────────────────────────────────────────

@app.post("/llm/{config_name}/chat-proxy")
async def llm_chat_proxy_endpoint(config_name: str, request: Request):
    ext_base = _get_ext_base()
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            r = await client.post(f"{ext_base}/llm/{config_name}/chat", json=body,
                headers={**_EXT_HEADERS, "Content-Type": "application/json"})
        if "html" in r.headers.get("content-type", ""):
            raise HTTPException(status_code=503, detail="Student tunnel not public")
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Student server offline: {ext_base}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── EXTERNAL CONFIG DETAIL & CHAT PROXY ──────────────────────────────────

@app.get("/external/config/{config_name}")
async def get_external_config_details(config_name: str):
    ext_base = _get_ext_base()
    if not ext_base:
        return {"error": "no_url", "detail": "No student server URL configured", "external_base": ""}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(f"{ext_base}/configs/{config_name}", headers=_EXT_HEADERS)
        if "html" in r.headers.get("content-type", ""):
            return {"error": "tunnel_auth", "detail": "Set Port Visibility to Public in VS Code Ports tab", "external_base": ext_base}
        data = r.json()
        data["_external_base"] = ext_base
        return data
    except httpx.ConnectError:
        return {"error": "offline", "detail": f"Cannot reach {ext_base}", "external_base": ext_base}
    except Exception as e:
        return {"error": str(e), "external_base": ext_base}

@app.post("/external/chat/{config_name}")
async def proxy_external_chat(config_name: str, request: Request):
    ext_base = _get_ext_base()
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            r = await client.post(f"{ext_base}/llm/{config_name}/chat", json=body, headers=_EXT_HEADERS)
        if "html" in r.headers.get("content-type", ""):
            return JSONResponse(status_code=503, content={"error": "Student tunnel not public"})
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

@app.get("/debug/external")
async def debug_external():
    ext_base = _get_ext_base()
    if not ext_base:
        return {"external_base": "", "error": "No URL set. Paste the student devtunnel URL in Step 4 → Server URL box."}
    results = {}
    for path in ["/configs", "/configs/active", "/health", "/"]:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(f"{ext_base}{path}", headers=_EXT_HEADERS)
            results[path] = {
                "status": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "is_html": "html" in r.headers.get("content-type", ""),
                "body": r.text[:400],
            }
        except Exception as e:
            results[path] = {"error": str(e)}
    return {"external_base": ext_base, "endpoints": results}


# ── SMART PROMPT PARSER ───────────────────────────────────────────────────

class ParsePromptRequest(BaseModel):
    prompt: str
    selected_config: Optional[str] = None

@app.post("/parse-prompt")
async def parse_prompt_endpoint(req: ParsePromptRequest):
    import re
    from src.utils.config_store import list_configs, get_config as _get_cfg
    from src.utils.router_manager import get_router

    SYSTEM = """You are a land investment form parser for India. Extract details from the user's description and return ONLY a valid JSON object -- no explanation, no markdown, no backticks.

JSON structure (use null for anything not mentioned):
{
  "state": "state name or null",
  "city": "city or null",
  "area": "locality/sector/area or null",
  "pincode": "pincode string or null",
  "land_size": number or null,
  "land_unit": "sq_yards|sq_ft|acres|bigha",
  "land_type": "residential|commercial|agricultural|industrial|mixed_use",
  "total_budget": number in rupees or null,
  "purpose": "buy_and_hold|construction|rental_income|resale_profit",
  "timeline_years": number or 5,
  "risk_tolerance": "conservative|moderate|aggressive",
  "taking_loan": false,
  "has_title_deed": true,
  "monthly_income_expectation": 0
}

Rules: 50 lakhs=5000000, 1 crore=10000000, 1.2 crore=12000000.
Infer state from city. build/construct=construction, rent/rental=rental_income, resale/flip=resale_profit.
Default: residential, buy_and_hold, moderate."""

    cfg_name = req.selected_config
    if not cfg_name:
        active = [c for c in list_configs() if c["status"] == "active"]
        cfg_name = active[0]["full_name"] if active else None

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Parse this: {req.prompt}"}
    ]
    text = None

    if cfg_name:
        try:
            router = get_router(cfg_name)
            if router:
                resp = await router.acompletion(
                    model=f"{cfg_name}::chat", messages=messages, max_tokens=400, temperature=0.1)
                text = resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"[PARSE] Router failed: {e}")

    if not text:
        try:
            import litellm
            for model in ["groq/llama3-8b-8192", "gemini/gemini-1.5-flash", "gpt-3.5-turbo"]:
                try:
                    resp = await litellm.acompletion(model=model, messages=messages, max_tokens=400, temperature=0.1)
                    text = resp.choices[0].message.content.strip()
                    break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[PARSE] Litellm fallback failed: {e}")

    if not text:
        raise HTTPException(status_code=503, detail="No LLM available to parse. Configure one at /static/llm-setup.html")

    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if not match:
        raise HTTPException(status_code=422, detail=f"Could not parse LLM response: {text[:200]}")

    try:
        fields = _json.loads(match.group())
        fields = {k: v for k, v in fields.items() if v is not None}
        return {"success": True, "fields": fields}
    except _json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="LLM returned invalid JSON")


# ── ENTRY POINT ────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════
#  LANGFLOW INTEGRATION — added by patch_langflow.py
# ══════════════════════════════════════════════════════
from src.utils.langflow_bridge import is_langflow_running, run_via_langflow, get_flow_id

# NOTE: /langflow/status is intentionally NOT defined here. It's served by
# langflow_router (src/utils/langflow_routes.py) below, which returns the
# richer {online, base_url, flow_id, agents_detected, mode} dict that
# frontend/langflow.html actually expects. A duplicate bool-returning
# /langflow/status used to be defined here and silently shadowed it.

@app.post("/langflow/run")
def run_langflow_pipeline(req: LandQueryRequest):
    """Run analysis through Langflow visual pipeline."""
    try:
        result = run_via_langflow(_json.dumps(req.model_dump()))
        if result is None:
            return {"success": False, "error": "Langflow flow returned no output", "note": "Visual canvas is available at localhost:7860"}
        if result is None:
            return {"success": False, "error": "Langflow flow returned no output", "note": "Visual canvas available at localhost:7860"}
        if result is None:
            return {"success": False, "error": "Langflow flow returned no output", "note": "Visual canvas available at localhost:7860"}
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e), "fallback": "use /analyse instead"}

@app.get("/langflow/flow-id")
def get_langflow_flow_id():
    """Return the configured Langflow flow ID."""
    from src.utils.langflow_bridge import _get_flow_id
    fid = _get_flow_id()
    return {"flow_id": fid or "not_configured"}

# ══════════════════════════════════════════════════════



# ── LANGFLOW_ROUTER_BLOCK — added by patch_api_langflow.py ──────────────
# Additive only. If this import fails, LandIQ boots exactly as before.
try:
    from src.utils.langflow_routes import langflow_router, internal_router
    app.include_router(langflow_router)
    app.include_router(internal_router)
    print("[Langflow] routes registered at /langflow/* and /internal/*")
except Exception as _langflow_exc:  # pragma: no cover
    print(f"[Langflow] routes not loaded ({_langflow_exc}) — local orchestrator unaffected")
# ── end LANGFLOW_ROUTER_BLOCK ──────────────────────────────────────────


# >>> LANDIQ_LANGFLOW_BLOCK_START
# =====================================================================
#  LANDIQ REGISTRY + LANGFLOW SUPPORT ENDPOINTS
#  Added by fix_api_paste.py - do not move below __main__
# =====================================================================

_REGISTRY_DIR = _Path("agents_registry")


def _safe_agent_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or ".." in name:
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


@app.post("/run-single-agent")
async def run_single_agent(request: Request):
    body = await request.json()
    agent_name = body.get("agent_name")
    state = body.get("state", {})
    try:
        from src.agents.dynamic_agent import run_dynamic_agent
        result = run_dynamic_agent(agent_name, state)
        return {"success": True, "agent": agent_name, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/rag-context")
async def rag_context(request: Request):
    body = await request.json()
    query = body.get("query", "")
    from src.rag.retriever import get_rag_context
    context = get_rag_context(query)
    return {"context": context}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
