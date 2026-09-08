"""
orchestrator_component_live.py — LandIQ Langflow Orchestrator (LIVE COPY)
-----------------------------------------------------------------------------
Exact copy of the "LandIQ Orchestrator" component's code as it actually runs
inside the live Langflow flow (id 8ec649ea-8452-4b5a-a4ec-0f266b759fc8),
pulled directly from Langflow's own API. Keep this in sync whenever the live
component is edited (in the Langflow UI, or via this project's own patch
scripts) — paste this file's contents back into the component's code editor
to restore/redeploy it.

This version is the real dynamic orchestrator: it reads the live property
query (injected via Langflow's tweaks API at run time, not a static per-node
default), asks an LLM to plan execution layers from the agent catalogue
(read live from agents_registry/), then dispatches each agent itself via
direct HTTP calls in that plan's real order — passing each completed
layer's real findings into the next layer as `previous_outputs`. Everything
after the agent dispatch loop (token accounting, the guardrail call, final
JSON serialization) is wrapped defensively: an earlier version let a
guardrail-server hiccup or a serialization edge case silently discard an
otherwise fully successful multi-agent run, forcing a full duplicate re-run
on the local fallback path. Now a failure anywhere in that tail is caught,
recorded in plain text on the response (`orchestrator_error` /
`guardrail_error` / `serialization_error`), and the real agent results
already gathered are never thrown away.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import DataInput, MessageTextInput, Output
from lfx.schema.message import Message
import json


class LandIQOrchestrator(Component):
    display_name = "LandIQ Orchestrator"
    description = (
        "The real dynamic orchestrator. Reads the live property query (injected "
        "via tweaks at run time, not a static default), asks the LLM to plan "
        "execution layers from the agent catalogue (read live from "
        "agents_registry/ - nothing hardcoded), then dispatches each agent in "
        "that plan's real order, passing each completed layer's real findings "
        "into the next layer. The orchestrator's own runtime decision determines "
        "who runs when and what they see - not a fixed canvas wiring."
    )
    icon = "brain"
    name = "LandIQOrchestrator"

    inputs = [
        MessageTextInput(name="query_input", display_name="Property Query (JSON)",
                         info="The real submitted property data, injected via tweaks at run time.",
                         value="{}"),
        DataInput(name="planner_config", display_name="Planner LLM", info="From the Orchestrator LLM box."),
        DataInput(name="guardrail_config", display_name="Guardrail", info="From the PII Safety Guardrail box."),
        MessageTextInput(name="agent_catalogue", display_name="Agent Catalogue",
                         info="Every agent found in agents_registry/, read at canvas-build time.",
                         value='- environmental_risk (layer 1): Analyses flood risk pollution green zone restrictions for Indian land\n- financial (layer 1): Calculates actual ROI, rental yield, capital appreciation and investment viability with specific INR numbers for Indian land.\n- legal (layer 1): Analyses title risk, RERA compliance, encumbrances, state land laws and legal red flags for Indian land transactions.\n- location (layer 1): Analyses location quality, connectivity, infrastructure, price trends and appreciation for Indian land.\n- market (layer 1): Analyses demand-supply dynamics, price momentum, market timing and buyer profile for the specific Indian micro-market.\n- area_crowd (layer 2): this agent analysis the crowd of type of people livenearby like it employes or businessmen or builders etc\n- bear (layer 2): Identifies specific downside risks, worst-case loss in INR and probability-weighted risk assessment for Indian land investment.\n- bull (layer 2): Constructs the best-case investment scenario with specific upside triggers, actual INR numbers and % returns.\n- due_diligence (layer 3): Cross-checks all agent findings, flags contradictions, identifies gaps and produces a consolidated risk score for the investment.\n- senior_consultant (layer 4): Final investment verdict — Buy, Hold, or Avoid — with negotiation price, specific conditions and investor action item.'),
    ]

    outputs = [
        Output(display_name="Final Analysis", name="final_result", method="orchestrate"),
    ]

    def orchestrate(self) -> Message:
        import httpx
        import time
        import traceback
        from concurrent.futures import ThreadPoolExecutor, as_completed

        BACKEND = "http://127.0.0.1:8000"
        state = {}

        # Everything from here down is wrapped so that once agents have run
        # and state is built, NOTHING later (guardrail call, token math,
        # serialization) can silently discard that real work. A previous
        # version let an exception anywhere after the agent loop wipe out an
        # otherwise fully successful 11-agent run, forcing a full duplicate
        # re-run on the local fallback path - this guarantees that can't
        # happen again, and if something still goes wrong, the real
        # exception text ends up IN the returned JSON instead of vanishing.
        try:
            try:
                raw_q = self.query_input if isinstance(self.query_input, str) else str(self.query_input)
                query = json.loads(raw_q) if raw_q and raw_q.strip() and raw_q.strip() != "{}" else {}
            except Exception:
                query = {}

            state = dict(query)
            state["completed_agents"] = []
            state["error_log"] = []

            planner = {}
            if self.planner_config is not None and getattr(self.planner_config, "data", None):
                planner = dict(self.planner_config.data)

            plan = {"layers": [], "source": "error"}
            try:
                r = httpx.post(
                    f"{BACKEND}/internal/run-orchestrated",
                    json={"property_data": query, "agent_catalogue": self.agent_catalogue,
                          "planning_model": planner.get("planning_model")},
                    timeout=90,
                )
                info = r.json()
                if info.get("plan", {}).get("layers"):
                    plan = info["plan"]
                if info.get("rag_context"):
                    state["rag_context"] = info["rag_context"]
            except Exception as e:
                state["plan_error"] = str(e)[:160]

            if not plan.get("layers"):
                plan = {
                    "layers": [
                        ["environmental_risk", "financial", "legal", "location", "market", "visual_document"],
                        ["area_crowd", "bear", "bull"],
                        ["due_diligence"],
                        ["senior_consultant"],
                    ],
                    "source": "default",
                }
            state["execution_plan"] = plan

            def merge_result(result):
                if not isinstance(result, dict):
                    return
                for k, v in result.items():
                    if k in ("completed_agents", "error_log"):
                        state[k] = state.get(k, []) + (v if isinstance(v, list) else [v])
                    else:
                        state[k] = v

            def run_one(agent_name, prev_snapshot, delay):
                time.sleep(delay)
                payload = dict(query)
                payload["agent_name"] = agent_name
                payload["previous_outputs"] = prev_snapshot
                try:
                    # /run-single-agent (no prefix) wraps the real agent
                    # output in {"success","agent","result"} - merge_result()
                    # then merged those wrapper keys instead of the actual
                    # "{agent}_output"/completed_agents fields inside
                    # "result", so every successful agent's real output was
                    # silently discarded and overwritten by the next one.
                    # /internal/run-single-agent returns run_dynamic_agent()'s
                    # dict directly (the shape merge_result() expects), and
                    # also adds real RAG + PixelRAG grounding this endpoint
                    # never had.
                    r = httpx.post(f"{BACKEND}/internal/run-single-agent", json=payload, timeout=180)
                    return r.json()
                except Exception as e:
                    return {"error_log": [f"{agent_name}: {str(e)[:150]}"],
                            "completed_agents": [f"{agent_name} (Failed)"]}

            total_start = time.time()
            state["layers_completed"] = []
            for layer_idx, layer_agents in enumerate(plan["layers"]):
                # Each layer gets its own try/except now. Before this, one
                # bad layer (an exception anywhere in its dispatch/merge)
                # threw all the way out to the outer handler, silently
                # abandoning every later layer - including Bull/Bear/Due
                # Diligence/Senior Consultant - with no record of which
                # layer or why. This keeps whatever layers DID finish, and
                # names the exact layer + error for whichever one didn't.
                try:
                    prev_snapshot = {k: v for k, v in state.items() if k.endswith("_output")}
                    if len(layer_agents) == 1:
                        merge_result(run_one(layer_agents[0], prev_snapshot, 0))
                    else:
                        with ThreadPoolExecutor(max_workers=min(2, len(layer_agents))) as ex:
                            futures = {ex.submit(run_one, name, prev_snapshot, i * 4.0): name
                                       for i, name in enumerate(layer_agents)}
                            for fut in as_completed(futures, timeout=420):
                                try:
                                    merge_result(fut.result(timeout=1))
                                except Exception as e:
                                    name = futures[fut]
                                    merge_result({"error_log": [f"{name}: {str(e)[:150]}"],
                                                  "completed_agents": [f"{name} (Failed)"]})
                    state["layers_completed"].append(layer_idx)
                except Exception as e:
                    state["error_log"] = state.get("error_log", []) + [
                        f"layer {layer_idx} {layer_agents}: {type(e).__name__}: {str(e)[:250]}"]
                    state["orchestrator_error"] = (
                        f"stopped at layer {layer_idx} {layer_agents}: "
                        f"{type(e).__name__}: {str(e)[:250]}")
                    # Keep going - a later layer failing shouldn't also
                    # silently erase an earlier layer's real results, and a
                    # later layer might still partially succeed even if an
                    # earlier one had trouble.
                    continue

            state["total_time_seconds"] = round(time.time() - total_start, 1)

            if state.get("senior_consultant_output"):
                state["final_recommendation"] = state["senior_consultant_output"]
            state["orchestrator_source"] = "langflow"
        except Exception as e:
            # Even if planning/dispatch itself blew up, keep whatever partial
            # state exists and record exactly what happened, in plain text,
            # instead of losing everything silently.
            state["orchestrator_error"] = f"{type(e).__name__}: {str(e)[:300]}"
            state.setdefault("orchestrator_source", "langflow")

        # Token report - defensive: a bad value in one agent's metadata must
        # not be able to take down the whole response.
        try:
            per_agent_log = []
            total_in = total_out = 0
            for key, val in list(state.items()):
                if key.endswith("_metadata") and isinstance(val, dict):
                    a_in = val.get("input_tokens", 0) or 0
                    a_out = val.get("output_tokens", 0) or 0
                    per_agent_log.append({
                        "agent": val.get("agent", key[:-9]),
                        "input_tokens": a_in, "output_tokens": a_out,
                        "total_tokens": val.get("total_tokens", a_in + a_out),
                    })
                    total_in += a_in
                    total_out += a_out
            state["token_report"] = {
                "input_tokens": total_in, "output_tokens": total_out,
                "total_tokens": total_in + total_out,
                "total_llm_calls": len(per_agent_log), "per_agent_log": per_agent_log,
            }
        except Exception as e:
            state["token_report_error"] = str(e)[:150]

        # Guardrail - defensive: a slow/misconfigured guardrail server must
        # not be able to take down an otherwise complete analysis.
        try:
            gr = {}
            if self.guardrail_config is not None and getattr(self.guardrail_config, "data", None):
                gr = dict(self.guardrail_config.data)
            mode = (gr.get("guardrail_mode") or "none").lower()

            if mode != "none":
                pii_action = "BLOCK" if mode == "block" else "MASK"
                text_to_check = str(state.get("final_recommendation") or "")[:4000]
                try:
                    gres = httpx.post(
                        (gr.get("guardrail_url") or "http://127.0.0.1:8002").rstrip("/") + "/run",
                        json={"text": text_to_check, "pii_enabled": True, "pii_action": pii_action,
                              "safety_enabled": True, "topic_check": False},
                        timeout=15,
                    )
                    gresult = gres.json()
                    state["guardrail_status"] = "checked"
                    state["guardrail_allowed"] = gresult.get("allowed")
                    state["guardrail_pii_found"] = gresult.get("pii_found")
                    state["guardrail_blocked_reason"] = gresult.get("blocked_reason")
                    if mode in ("redact", "block") and gresult.get("processed_text"):
                        state["final_recommendation"] = gresult["processed_text"]
                except Exception as e:
                    state["guardrail_status"] = "server_offline"
                    state["guardrail_error"] = str(e)[:150]
            else:
                state["guardrail_status"] = "skipped"
        except Exception as e:
            state["guardrail_status"] = "error"
            state["guardrail_error"] = str(e)[:150]

        self.status = state
        try:
            text = json.dumps(state, default=str)
        except Exception as e:
            # Absolute last resort: never let serialization itself be the
            # thing that throws away a fully-built, real analysis.
            text = json.dumps({
                "orchestrator_source": "langflow",
                "serialization_error": f"{type(e).__name__}: {str(e)[:200]}",
                "completed_agents": state.get("completed_agents", []),
            }, default=str)
        return Message(text=text)
