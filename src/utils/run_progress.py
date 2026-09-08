"""
run_progress.py
----------------
Real-time progress for the currently running /analyse call, so the frontend
loading screen can show what is ACTUALLY happening instead of a canned
cycling message. api.py's own single-run guard (_analysis_in_progress)
already ensures only one analysis runs at a time, so one module-level dict
is enough — no per-run id plumbing needed.

Written to by src/graph/orchestrator_agent.py as the run progresses, read by
the GET /analyse/progress endpoint in api.py. Never raises — a progress
update failing must never break the actual analysis.
"""

import threading
import time

_lock = threading.Lock()

_state = {
    "status": "idle",          # idle | planning | running | done | error
    "plan_source": None,       # "llm" | "default"
    "layers_plan": [],         # [[agent, ...], ...] full plan
    "layer_index": -1,         # 0-based index of the currently running layer
    "total_layers": 0,
    "current_layer_agents": [],
    "completed_agents": [],    # display names, in completion order
    "total_agents": 0,
    "started_at": None,
    "elapsed_seconds": 0,
}


def reset():
    with _lock:
        _state.update({
            "status": "planning",
            "plan_source": None,
            "layers_plan": [],
            "layer_index": -1,
            "total_layers": 0,
            "current_layer_agents": [],
            "completed_agents": [],
            "total_agents": 0,
            "started_at": time.time(),
            "elapsed_seconds": 0,
        })


def set_plan(layers, source):
    try:
        with _lock:
            _state["layers_plan"] = layers
            _state["total_layers"] = len(layers)
            _state["total_agents"] = sum(len(l) for l in layers)
            _state["plan_source"] = source
            _state["status"] = "running"
    except Exception:
        pass


def start_layer(index, agent_names):
    try:
        with _lock:
            _state["layer_index"] = index
            _state["current_layer_agents"] = list(agent_names)
    except Exception:
        pass


def agent_done(display_name):
    try:
        with _lock:
            _state["completed_agents"].append(display_name)
    except Exception:
        pass


def finish(status="done"):
    try:
        with _lock:
            _state["status"] = status
    except Exception:
        pass


def get():
    with _lock:
        snap = dict(_state)
    if snap["started_at"]:
        snap["elapsed_seconds"] = round(time.time() - snap["started_at"], 1)
    return snap
