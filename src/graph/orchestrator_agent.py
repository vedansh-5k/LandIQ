"""
orchestrator_agent.py  —  FINAL

- Pre-flight probes external gateway AND loads tpr caps
- Planner always uses local Groq (never the tunnel)
- 2 workers, 4s stagger (stays under Groq free-tier TPM)
- Layer never raises — dead provider degrades the report, not the run
"""

import json, time, os, logging, traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


def _load_env():
    current = Path(__file__).resolve().parent
    for _ in range(6):
        env_file = current / ".env"
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = val
            return
        current = current.parent

_load_env()

from src.utils.agent_loader import get_agent_catalogue

_TC = None
try:
    from src.utils import tracked_chain as _TC
except Exception as _e:
    print("  [TOKENS] tracked_chain import failed: %r" % (_e,))


def _tc_call(fn_name, *args):
    if _TC is None:
        return False, None
    fn = getattr(_TC, fn_name, None)
    if fn is None:
        return False, None
    try:
        return True, fn(*args)
    except Exception as e:
        print("  [TOKENS] %s() error: %r" % (fn_name, e))
        return False, None


DEFAULT_PLAN = {
    "layers": [
        ["location", "legal", "financial", "market"],
        ["bull", "bear"],
        ["due_diligence"],
        ["senior_consultant"],
    ]
}

PLANNER_SYSTEM_PROMPT = """You are the ORCHESTRATOR of LandIQ.
You have FULL AUTHORITY to decide which agents run and in what order.

Return ONLY this JSON (no markdown, no explanation):
{"layers": [["agent1","agent2"], ["agent3"], ["agent4"]]}

RULES:
- Same list = parallel execution
- location/legal/financial/market are independent -> Layer 1
- bull/bear need Layer 1 results -> Layer 2
- due_diligence needs everything -> near end
- senior_consultant ALWAYS last, alone
- Only include agents from the user's selection (or all if "all")
- Return ONLY the JSON."""


def _probe_external(base_url, timeout=6):
    if not base_url:
        return False, "no external base url"
    try:
        import requests
    except Exception:
        return False, "requests not installed"
    try:
        r = requests.get(base_url.rstrip("/") + "/configs",
                         headers={"Accept": "application/json",
                                  "X-Tunnel-Skip-Auth-Redirect": "true"},
                         timeout=timeout)
        if "html" in (r.headers.get("content-type") or "").lower():
            return False, "devtunnel returned HTML (set Port Visibility Public)"
        if r.status_code != 200:
            return False, "HTTP %s" % r.status_code
        return True, "HTTP 200"
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:70])


def _disable_external(tls, ext_name):
    for attr in ("external_config", "external_base"):
        try:
            setattr(tls, attr, None)
        except Exception:
            pass
    try:
        if getattr(tls, "selected_config", None) == ext_name:
            tls.selected_config = None
    except Exception:
        pass
    try:
        tls.force_local = True
    except Exception:
        pass


def _get_planner_llm():
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            from langchain_groq import ChatGroq
            llm = ChatGroq(api_key=groq_key,
                           model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                           temperature=0.1, timeout=45, max_retries=1)
            print("  [ORCHESTRATOR] Planner LLM: ChatGroq (local)")
            return llm
        except Exception as e:
            print("  [ORCHESTRATOR] Groq planner failed: %s" % str(e)[:80])

    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                google_api_key=google_key,
                model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
                temperature=0.1)
            print("  [ORCHESTRATOR] Planner LLM: Gemini (local)")
            return llm
        except Exception as e:
            print("  [ORCHESTRATOR] Gemini planner failed: %s" % str(e)[:80])

    raise RuntimeError("No local API key for planner")


def plan_execution(user_inputs):
    catalogue = get_agent_catalogue()
    selected = user_inputs.get("selected_agents", ["all"])
    valid = {a["name"] for a in catalogue}

    cat_text = "\n".join(
        "- %s (layer %s): %s" % (a["name"], a["layer"], a["description"][:70])
        for a in sorted(catalogue, key=lambda x: x["layer"]))

    print("\n  [ORCHESTRATOR] Agents available: %s" % sorted(valid))
    print("  [ORCHESTRATOR] User selected: %s" % selected)

    try:
        llm = _get_planner_llm()
        user_text = (
            "AVAILABLE AGENTS:\n%s\n\n"
            "ANALYSE: %s %s in %s, %s, %s. Budget INR %s. Purpose: %s.\n"
            "SELECTED: %s\n\nReturn JSON plan now."
        ) % (cat_text, user_inputs.get("land_size"), user_inputs.get("land_unit"),
             user_inputs.get("area"), user_inputs.get("city"), user_inputs.get("state"),
             user_inputs.get("total_budget"), user_inputs.get("purpose"), selected)

        raw = llm.invoke([("system", PLANNER_SYSTEM_PROMPT), ("human", user_text)])
        text = raw.content if hasattr(raw, "content") else str(raw)
        text = text.strip()
        for prefix in ("```json", "```", "json"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        text = text.strip("`").strip()

        plan_data = json.loads(text)
        layers = [[a for a in layer if a in valid]
                  for layer in plan_data.get("layers", [])]
        layers = [l for l in layers if l]
        if not layers:
            raise ValueError("No valid agents in plan")

        print("  [ORCHESTRATOR] LLM PLAN: %s" % layers)
        return {"layers": layers, "source": "llm"}

    except Exception as e:
        print("  [ORCHESTRATOR] Planning failed: %s" % str(e)[:110])
        print("  [ORCHESTRATOR] Using default plan")

        if "all" in selected:
            default_agents = set()
            for layer in DEFAULT_PLAN["layers"]:
                default_agents.update(layer)
            extra = valid - default_agents
            layers = [list(l) for l in DEFAULT_PLAN["layers"]]
            if extra:
                layers[0] = layers[0] + sorted(extra)
        else:
            layers = []
            for layer in DEFAULT_PLAN["layers"]:
                kept = [a for a in layer
                        if (a in selected or a == "senior_consultant") and a in valid]
                if kept:
                    layers.append(kept)
            if not layers:
                layers = [list(l) for l in DEFAULT_PLAN["layers"]]

        print("  [ORCHESTRATOR] Default plan: %s" % layers)
        return {"layers": layers, "source": "default"}


def _merge(results, out):
    if not isinstance(out, dict):
        return
    for k, v in out.items():
        if k in ("completed_agents", "error_log") and k in results:
            results[k] = results[k] + (v if isinstance(v, list) else [v])
        else:
            results[k] = v


def _run_layer(agent_names, state):
    from src.agents.dynamic_agent import run_dynamic_agent
    from src.utils.llm_factory import _tls as _factory_tls

    _sel_cfg  = getattr(_factory_tls, "selected_config", None)
    _ext_cfg  = getattr(_factory_tls, "external_config", None)
    _ext_base = getattr(_factory_tls, "external_base", None)
    _force    = getattr(_factory_tls, "force_local", False)

    def _propagate():
        _factory_tls.selected_config = _sel_cfg
        _factory_tls.external_config = _ext_cfg
        _factory_tls.external_base   = _ext_base
        _factory_tls.force_local     = _force

    if len(agent_names) == 1:
        _propagate()
        try:
            return run_dynamic_agent(agent_names[0], state)
        except Exception as e:
            print("  [AGENT ERROR] %s: %s" % (agent_names[0], str(e)[:100]))
            return {"error_log": ["%s failed: %s" % (agent_names[0], str(e)[:140])],
                    "completed_agents": ["%s (Failed)" % agent_names[0]]}

    results = {}

    def run_one(name, delay):
        _propagate()
        time.sleep(delay)
        try:
            return run_dynamic_agent(name, state)
        except Exception as e:
            print("  [AGENT ERROR] %s: %s" % (name, str(e)[:100]))
            return {"error_log": ["%s failed: %s" % (name, str(e)[:140])],
                    "completed_agents": ["%s (Failed)" % name]}

    # 2 workers, 4s stagger -> stays under Groq free-tier TPM
    ex = ThreadPoolExecutor(max_workers=min(2, len(agent_names)))
    try:
        futures = {ex.submit(run_one, n, i * 4.0): n
                   for i, n in enumerate(agent_names)}
        seen = set()
        try:
            for fut in as_completed(futures, timeout=420):
                seen.add(fut)
                name = futures[fut]
                try:
                    _merge(results, fut.result(timeout=10))
                except Exception as e:
                    print("  [AGENT ERROR] %s: %s" % (name, str(e)[:100]))
                    _merge(results, {
                        "error_log": ["%s failed: %s" % (name, str(e)[:140])],
                        "completed_agents": ["%s (Failed)" % name]})
        except Exception as e:
            print("  [LAYER] wait ended early: %s" % str(e)[:110])
            for fut, name in futures.items():
                if fut in seen:
                    continue
                if fut.done():
                    try:
                        _merge(results, fut.result(timeout=1))
                        continue
                    except Exception:
                        pass
                fut.cancel()
                _merge(results, {"error_log": ["%s timed out" % name],
                                 "completed_agents": ["%s (Timeout)" % name]})
    finally:
        ex.shutdown(wait=False)

    return results


def run_dynamic_advisor(user_inputs):
    state = dict(user_inputs)
    state.setdefault("completed_agents", [])
    state.setdefault("error_log", [])

    session_start = time.time()
    start_clock = time.strftime("%H:%M:%S")
    _tc_call("reset_token_report")

    print("\n" + "#" * 55)
    print("# LANDIQ ORCHESTRATOR - %s, %s" % (state.get("area"), state.get("city")))
    print("#" * 55)

    # ── 0/3: EXTERNAL PRE-FLIGHT ─────────────────────────────────────
    print("\n  [0/3] External gateway pre-flight...")
    ext_status = {"requested": False, "alive": False, "reason": "not requested",
                  "config": None, "base": None}
    try:
        from src.utils import llm_factory as _lf
        _tls = _lf._tls
        ext_cfg  = getattr(_tls, "external_config", None)
        ext_base = getattr(_tls, "external_base", None)
        ext_name = getattr(_tls, "selected_config", None)

        if ext_cfg or ext_base:
            ext_status["requested"] = True
            ext_status["config"] = ext_cfg or ext_name
            ext_status["base"] = ext_base
            alive, reason = _probe_external(ext_base)
            ext_status["alive"] = alive
            ext_status["reason"] = reason
            if alive:
                print("  [0/3] External gateway ALIVE -> '%s'" % (ext_cfg or ext_name))
                # Load tpr caps BEFORE agents run
                try:
                    _lf.load_external_caps(ext_cfg or ext_name, ext_base)
                except Exception as e:
                    print("  [0/3] Cap load skipped: %s" % str(e)[:80])
            else:
                print("  " + "!" * 51)
                print("  ! EXTERNAL GATEWAY OFFLINE: %s" % reason)
                print("  ! FALLING BACK TO LOCAL LLM.")
                print("  " + "!" * 51)
                _disable_external(_tls, ext_name)
        else:
            print("  [0/3] No external config - running local.")
    except Exception as e:
        print("  [0/3] Pre-flight skipped: %s" % str(e)[:90])

    state["external_status"] = ext_status

    # ── 1/3: RAG ─────────────────────────────────────────────────────
    print("\n  [1/3] RAG context...")
    try:
        from src.rag.retriever import get_rag_context
        q = "%s %s %s %s land" % (state.get("area", ""), state.get("city", ""),
                                   state.get("state", ""), state.get("land_type", ""))
        state["rag_context"] = get_rag_context(q)
        print("  [1/3] RAG done")
    except Exception as e:
        state["rag_context"] = "No context available."
        print("  [1/3] RAG failed: %s" % str(e)[:60])

    # ── 2/3: Planning (ALWAYS local) ─────────────────────────────────
    print("\n  [2/3] Planning...")
    plan = plan_execution(user_inputs)
    state["execution_plan"] = plan
    state["_orch_plan"] = {
        "layers": plan["layers"], "source": plan["source"],
        "total_agents": sum(len(l) for l in plan["layers"]),
        "total_layers": len(plan["layers"]),
    }

    # ── 3/3: Execute ─────────────────────────────────────────────────
    print("\n  [3/3] Executing %d layers (plan=%s)..."
          % (len(plan["layers"]), plan["source"]))

    for i, layer in enumerate(plan["layers"], 1):
        print("\n  [Layer %d] %s" % (i, layer))
        t0 = time.time()
        try:
            out = _run_layer(layer, state)
        except Exception as e:
            print("  [Layer %d] CRASHED: %s" % (i, str(e)[:120]))
            out = {"error_log": ["Layer %d crashed: %s" % (i, str(e)[:120])],
                   "completed_agents": ["%s (Failed)" % n for n in layer]}
        print("  [Layer %d] done in %.1fs" % (i, time.time() - t0))

        for k, v in out.items():
            if k in ("completed_agents", "error_log"):
                state[k] = state.get(k, []) + (v if isinstance(v, list) else [v])
            else:
                state[k] = v

    sc = state.get("senior_consultant_output")
    if sc is not None:
        state["final_recommendation"] = sc
    elif state.get("due_diligence_output"):
        state["final_recommendation"] = state["due_diligence_output"]

    session_duration = round(time.time() - session_start, 2)
    end_clock = time.strftime("%H:%M:%S")

    ok, tokens = _tc_call("get_token_report")
    if ok and tokens:
        _tc_call("print_token_report")
    else:
        tokens = {"total_llm_calls": 0, "input_tokens": 0, "output_tokens": 0,
                  "total_tokens": 0, "estimated_cost_usd": 0, "per_agent_log": []}

    tokens["session_duration_seconds"] = session_duration
    tokens["start_time"] = start_clock
    tokens["end_time"] = end_clock
    state["token_report"] = tokens
    state["timing"] = {"start_time": start_clock, "end_time": end_clock,
                       "total_seconds": session_duration}

    try:
        from src.utils.mlflow_tracker import log_analysis_run
        log_analysis_run(state)
        state["mlflow_logged"] = True
    except Exception as e:
        state["mlflow_logged"] = False

    completed = state.get("completed_agents", [])
    errors = state.get("error_log", [])
    print("\n" + "#" * 55)
    print("# DONE - plan=%s | agents=%d | errors=%d | %ss" % (
        plan["source"], len(completed), len(errors), session_duration))
    print("# External: requested=%s alive=%s (%s)" % (
        ext_status["requested"], ext_status["alive"], ext_status["reason"]))
    print("# Completed: %s" % completed)
    if errors:
        print("# Errors: %s" % errors)
    print("#" * 55 + "\n")

    return state