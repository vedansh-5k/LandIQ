"""
langflow_routes.py  —  src/utils/langflow_routes.py

Every Langflow endpoint LandIQ exposes, as two APIRouters:
  langflow_router  -> /langflow/*   (status, flows, plan, run)
  internal_router  -> /internal/*   (called BY Langflow components back into LandIQ)

Nothing here touches existing LandIQ code. If this file is missing or
broken, api.py still boots and every old endpoint works unchanged.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.utils import langflow_bridge as lf

logger = logging.getLogger(__name__)

langflow_router = APIRouter(prefix="/langflow", tags=["Langflow"])
internal_router = APIRouter(prefix="/internal", tags=["Langflow Internal"])


# ── shared helpers ──────────────────────────────────────────────────────
def safe_dump(obj: Any) -> Any:
    """Module-level version of api.py's _safe_dump (that one is function-local)."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    return {"summary": str(obj)}


async def _off(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _discover_agents() -> List[str]:
    """Live agent registry — nothing hardcoded."""
    try:
        from src.utils.agent_loader import get_agent_catalogue
        cat = get_agent_catalogue()
        if isinstance(cat, dict):
            return sorted(cat.keys())
        if isinstance(cat, list):
            out = []
            for a in cat:
                if isinstance(a, str):
                    out.append(a)
                elif isinstance(a, dict):
                    n = a.get("name") or a.get("agent_name") or a.get("id")
                    if n:
                        out.append(str(n))
            return sorted(set(out))
    except Exception:
        pass
    try:
        reg = lf.ROOT / "agents_registry"
        if reg.is_dir():
            return sorted(p.name for p in reg.iterdir()
                          if p.is_dir() and not p.name.startswith((".", "_")))
    except Exception:
        pass
    return []


# ── request models ──────────────────────────────────────────────────────
class SetUrlRequest(BaseModel):
    base_url: str = Field(description="e.g. http://127.0.0.1:7860")
    api_key: Optional[str] = None


class SetFlowRequest(BaseModel):
    flow_id: str
    flow_name: Optional[str] = None


class RunRequest(BaseModel):
    input_value: str
    flow_id: Optional[str] = None
    tweaks: Optional[Dict[str, Any]] = None
    timeout: float = 120.0


class PlanRequest(BaseModel):
    query: str
    available_agents: Optional[List[str]] = None


# ══════════════════════════════════════════════════════════════════════
#  /langflow/*
# ══════════════════════════════════════════════════════════════════════
@langflow_router.get("/status")
async def langflow_status():
    data = await _off(lf.status)
    data["agents_detected"] = _discover_agents()
    return data


@langflow_router.get("/health")
async def langflow_health():
    return await _off(lf.health, True)


@langflow_router.get("/flows")
async def langflow_flows():
    return await _off(lf.list_flows)


@langflow_router.get("/flow-graph")
async def langflow_flow_graph(flow_id: Optional[str] = None):
    return await _off(lf.flow_graph, flow_id)


@langflow_router.get("/config")
async def langflow_config():
    return {
        "base_url": lf.get_base_url(),
        "flow_name": lf.get_flow_name(),
        "flow_id": lf._stored_flow_id(),
        "api_key_set": bool(lf.get_api_key()),
        "state_file": str(lf.STATE_FILE),
    }


@langflow_router.post("/set-url")
async def langflow_set_url(req: SetUrlRequest):
    lf.set_base_url(req.base_url)
    if req.api_key is not None:
        lf.set_api_key(req.api_key)
    lf._HEALTH_CACHE.update({"ts": 0.0, "data": None})
    data = await _off(lf.status)
    data["agents_detected"] = _discover_agents()
    return data


@langflow_router.post("/set-flow")
async def langflow_set_flow(req: SetFlowRequest):
    lf.set_flow_id(req.flow_id, req.flow_name)
    return await _off(lf.status)


@langflow_router.post("/run")
async def langflow_run(req: RunRequest):
    return await _off(lambda: lf.run_flow(
        req.input_value, flow_id=req.flow_id,
        tweaks=req.tweaks, timeout=req.timeout))


@langflow_router.post("/plan")
async def langflow_plan(req: PlanRequest):
    """
    Langflow builds the multi-agent execution plan.
    ok=False is not a failure for LandIQ — the local planner is used instead.
    """
    agents = req.available_agents or _discover_agents()
    result = await _off(lf.plan_execution, req.query, agents)
    result["available_agents"] = agents
    if not result.get("ok"):
        result["fallback"] = "local orchestrator planner (unchanged)"
    return result


# ══════════════════════════════════════════════════════════════════════
#  /internal/*  — Langflow components call these back into LandIQ
# ══════════════════════════════════════════════════════════════════════
@internal_router.post("/run-single-agent")
async def run_single_agent(request: Request):
    """Run ONE agent. A Langflow node hits this with the agent name."""
    body = await request.json()
    agent_name = (body.get("agent_name") or "").strip()
    if not agent_name:
        raise HTTPException(status_code=400, detail="agent_name required")

    known = _discover_agents()
    if known and agent_name not in known:
        raise HTTPException(
            status_code=404,
            detail="Agent '%s' is not in the registry. Available: %s"
                   % (agent_name, ", ".join(known)))

    # Pass through the FULL body as state - not a hand-picked field subset.
    # A narrow whitelist here was silently dropping land_size/land_unit/
    # timeline_years/risk_tolerance/etc (and any *_output keys a caller
    # merges in directly, e.g. Langflow agent nodes) before they ever
    # reached the agent's prompt - "Property Data" looked wired but was
    # actually arriving mostly empty. `location` -> `area` and
    # `previous_outputs` nesting are kept for backward compatibility with
    # older callers.
    state = dict(body)
    state.pop("agent_name", None)
    if not state.get("area"):
        state["area"] = body.get("location", "")
    state.setdefault("completed_agents", [])
    state.setdefault("error_log", [])

    prev = body.get("previous_outputs", {})
    if isinstance(prev, str):
        try:
            prev = _json.loads(prev)
        except Exception:
            prev = {}
    if isinstance(prev, dict):
        state.update(prev)

    # Individual Langflow canvas nodes (Agent_<name>) call this endpoint
    # directly with only property_data/prompt/llm/skill - none of them
    # carry real RAG context or PixelRAG visual evidence, so every agent
    # was silently running ungrounded. Fetch both here, once, server-side,
    # so every caller of this endpoint gets the same real grounding the
    # local orchestrator path already has - no canvas rewiring needed.
    if not (state.get("rag_context") or "").strip() or state["rag_context"] == "No context available.":
        try:
            from src.rag.retriever import get_rag_context, build_land_query
            query = build_land_query(state)
            state["rag_context"] = await _off(get_rag_context, query)
        except Exception as e:
            logger.warning("rag_context fetch failed for %s: %s", agent_name, str(e)[:150])
            state.setdefault("rag_context", "No context available.")

    if not state.get("visual_evidence"):
        try:
            from src.agents.dynamic_agent import _load_agent
            agent_meta = _load_agent(agent_name)
            if agent_meta and agent_meta.get("accepts_images"):
                from src.utils.pixelrag_bridge import search as pixelrag_search
                query = "%s %s %s %s land" % (
                    state.get("area", ""), state.get("city", ""),
                    state.get("state", ""), state.get("land_type", ""))
                hits = await _off(pixelrag_search, query, 4, True)
                if hits:
                    state["visual_evidence"] = hits
        except Exception as e:
            logger.warning("visual_evidence fetch failed for %s: %s", agent_name, str(e)[:150])

    try:
        from src.agents.dynamic_agent import run_dynamic_agent
        return safe_dump(run_dynamic_agent(agent_name, state))
    except Exception as e:
        logger.exception("single agent failed")
        return {"error": str(e), "agent": agent_name}


@internal_router.post("/run-full-pipeline")
async def run_full_pipeline(request: Request):
    """
    Run the exact same production pipeline as POST /analyse.

    Langflow is a real trigger for the real orchestrator here, not a second
    reimplementation of it: same LLM-config activation, same dynamic
    agents_registry discovery + LLM planner, same guardrails (classmate's
    PII component), same MLflow logging. Any future change to /analyse
    automatically applies to the Langflow path too - nothing to keep in sync.
    """
    body = await request.json()
    try:
        from api import analyse_land, LandQueryRequest
        req = LandQueryRequest(**body)
        req.skip_langflow = True  # this call IS the Langflow path — never re-trigger it
        result = await analyse_land(req)
        result["orchestrator_source"] = "langflow"
        return result
    except Exception as e:
        logger.exception("pipeline failed")
        return {"status": "error", "error": str(e)}


@internal_router.post("/run-orchestrated")
async def run_orchestrated(request: Request):
    """
    Real planning step for the Langflow "LandIQ Orchestrator" node's dispatch
    output - reuses the exact same plan_execution() the local orchestrator
    uses (src/graph/orchestrator_agent.py, same import langflow_bridge.py's
    own plan_execution() wrapper already uses), so the plan shown on the
    canvas is never a separate reimplementation. Also fetches real RAG
    context, exactly like run_dynamic_advisor()'s own first step.

    Deliberately does NOT execute any agents itself. run_dynamic_advisor()
    runs all 10 agents internally in one call; if this endpoint called that
    AND the canvas separately dispatched to 10 individually-wired agent
    nodes, either everything would run twice (double tokens/time) or the
    visible agent boxes would be decorative and not actually produce the
    result. Scoping this to planning + context only keeps the canvas wiring
    the sole, honest source of the final result - each agent node's own
    real call to /internal/run-single-agent is what runs it.
    """
    body = await request.json()
    query = body.get("property_data") or {}
    if isinstance(query, str):
        try:
            query = _json.loads(query)
        except Exception:
            query = {}

    plan = {"layers": [], "source": "error"}
    try:
        from src.graph.orchestrator_agent import plan_execution
        planning_query = dict(query)
        planning_query.setdefault("selected_agents", ["all"])
        plan = plan_execution(planning_query)
    except Exception as e:
        logger.warning("run-orchestrated: planning failed: %s", str(e)[:150])

    rag_context = "No context available."
    try:
        from src.rag.retriever import get_rag_context
        q = "%s %s %s %s land" % (query.get("area", ""), query.get("city", ""),
                                   query.get("state", ""), query.get("land_type", ""))
        rag_context = get_rag_context(q)
    except Exception as e:
        logger.warning("run-orchestrated: RAG lookup failed: %s", str(e)[:150])

    return {"plan": plan, "rag_context": rag_context}