"""
src/utils/mlflow_tracker.py
Logs every LandIQ analysis run to MLflow on DagsHub.
Tracks: config used, tokens, cost, agents, duration, caveman/guardrail settings.

Safe by design: if MLflow/DagsHub is unreachable or not configured,
it silently skips — your /analyse endpoint NEVER breaks because of tracking.
"""
import os
import logging

logger = logging.getLogger(__name__)

# ── Config (set these in your .env) ─────────────────────────────────────────
DAGSHUB_USER = os.environ.get("DAGSHUB_USER", "")
DAGSHUB_REPO = os.environ.get("DAGSHUB_REPO", "landiq")
DAGSHUB_TOKEN = os.environ.get("DAGSHUB_TOKEN", "")

# Full MLflow tracking URI on DagsHub
MLFLOW_URI = f"https://dagshub.com/{DAGSHUB_USER}/{DAGSHUB_REPO}.mlflow" if DAGSHUB_USER else ""

_mlflow_ready = False
_mlflow = None


def init_mlflow():
    """Call once at startup. Returns True if MLflow is ready."""
    global _mlflow_ready, _mlflow
    if not DAGSHUB_USER or not DAGSHUB_TOKEN:
        logger.info("[MLFLOW] DagsHub not configured (set DAGSHUB_USER/TOKEN in .env) — tracking disabled.")
        return False
    try:
        import mlflow
        os.environ["MLFLOW_TRACKING_USERNAME"] = DAGSHUB_USER
        os.environ["MLFLOW_TRACKING_PASSWORD"] = DAGSHUB_TOKEN
        mlflow.set_tracking_uri(MLFLOW_URI)
        mlflow.set_experiment("landiq_analysis")
        _mlflow = mlflow
        _mlflow_ready = True
        logger.info(f"[MLFLOW] Connected to {MLFLOW_URI}")
        return True
    except Exception as e:
        logger.warning(f"[MLFLOW] Init failed (tracking disabled): {e}")
        return False


def log_analysis_run(user_inputs: dict, final_state: dict, result: dict):
    """
    Log a single LandIQ analysis run. Called at the end of /analyse.
    Never raises — wraps everything in try/except.
    """
    if not _mlflow_ready or _mlflow is None:
        return
    try:
        tr = final_state.get("token_report", {}) or {}
        completed = final_state.get("completed_agents", []) or []
        dynamic = result.get("dynamic_agents", {}) or {}

        with _mlflow.start_run(run_name=f"{user_inputs.get('city','?')}_{user_inputs.get('area','?')}"):
            # ── Parameters (the "inputs") ──
            _mlflow.log_param("state", user_inputs.get("state"))
            _mlflow.log_param("city", user_inputs.get("city"))
            _mlflow.log_param("area", user_inputs.get("area"))
            _mlflow.log_param("land_type", user_inputs.get("land_type"))
            _mlflow.log_param("purpose", user_inputs.get("purpose"))
            _mlflow.log_param("llm_config", result.get("llm_configuration", "default"))
            _mlflow.log_param("llm_source", result.get("llm_source", "local"))
            _mlflow.log_param("caveman_mode", result.get("caveman_mode", False))
            _mlflow.log_param("caveman_level", result.get("caveman_level", "off"))
            _mlflow.log_param("num_agents", len(completed))
            _mlflow.log_param("num_dynamic_agents", len(dynamic))

            # ── Metrics (the numbers you can chart) ──
            def _n(*keys):
                for k in keys:
                    v = tr.get(k)
                    if v is not None:
                        try: return float(v)
                        except: pass
                return 0.0
            _mlflow.log_metric("input_tokens", _n("input_tokens", "total_input_tokens", "prompt_tokens"))
            _mlflow.log_metric("output_tokens", _n("output_tokens", "total_output_tokens", "completion_tokens"))
            _mlflow.log_metric("total_tokens", _n("total_tokens", "total"))
            _mlflow.log_metric("estimated_cost_usd", _n("estimated_cost_usd", "total_cost", "cost"))
            _mlflow.log_metric("duration_seconds", _n("session_duration_seconds", "duration_seconds", "elapsed_seconds"))
            _mlflow.log_metric("llm_calls", _n("total_llm_calls", "llm_calls", "calls") or len(completed))

            # ── Tags ──
            _mlflow.set_tag("agents_ran", ", ".join(str(a) for a in completed))
            if dynamic:
                _mlflow.set_tag("dynamic_agents", ", ".join(dynamic.keys()))
            rec = result.get("recommendation") or {}
            if rec.get("final_verdict"):
                _mlflow.set_tag("verdict", rec["final_verdict"])

        logger.info("[MLFLOW] Logged analysis run.")
    except Exception as e:
        logger.warning(f"[MLFLOW] Logging failed (ignored): {e}")


def is_ready() -> bool:
    return _mlflow_ready