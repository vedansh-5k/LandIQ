"""
orchestrator_component_v2.py — LandIQ Langflow Orchestrator (LAYER OUTPUTS)
-----------------------------------------------------------------------------
Paste this whole file's contents into the "LandIQ Orchestrator" component's
code editor in Langflow (replacing the old code) to switch it from 2 outputs
to 6 outputs, so each execution layer can be wired to its own agent nodes
on the canvas.

WHAT CHANGED vs orchestrator_component.py (the backup):
  - Same 1 input: Query JSON (query_input).
  - Outputs went from 2 -> 6:
        Layer 1 Result  (Data)     - agents_registry-discovered layer-1 agents
        Layer 2 Result  (Data)     - layer-2 agents
        Layer 3 Result  (Data)     - layer-3 agents
        Layer 4 Result  (Data)     - layer-4 agents (+ any layer beyond 4,
                                      merged in here so nothing is dropped if
                                      the LLM plans more than 4 layers)
        Final Result    (Data)     - the complete combined result (same shape
                                      as the old "Analysis Result" output)
        Final Message   (Message)  - same as the old "Result Message" output
  - Catalogue reading, LLM planning (_plan_execution/_call_llm_for_plan),
    the default-plan fallback, and per-agent execution via
    POST /run-single-agent are UNCHANGED. Nothing here is agent-name
    hardcoded: the number of layers and which agents land in which layer is
    decided entirely by the LLM plan (or, if the LLM fails, by each agent's
    own `layer:` field in its AGENT.md) exactly as before.
  - The whole pipeline still runs only ONCE per component execution: the
    first output Langflow evaluates triggers `_run_full_pipeline()`, which
    caches per-layer + final results on the instance; every other output
    method just reads the cache.
"""

from langflow.custom import Component
from langflow.io import HandleInput, Output
from langflow.schema import Data
from langflow.schema.message import Message
import json
import os
import time

PROJECT_ROOT = r"C:\Users\HP\OneDrive\Desktop\ai_boardroom_v3"
AGENTS_DIR = os.path.join(PROJECT_ROOT, "agents_registry")
BACKEND_URL = "http://127.0.0.1:8000"

NUM_LAYER_OUTPUTS = 4  # Layer 1..4 Result outputs on the canvas


class LandIQOrchestrator(Component):
    display_name = "LandIQ Orchestrator"
    description = (
        "Dynamic orchestrator: reads agent catalogue, "
        "asks LLM to plan execution layers, runs agents "
        "according to plan. Zero hardcoding. Exposes each "
        "execution layer as its own output so it can be wired "
        "to individual agent nodes on the canvas."
    )
    icon = "brain"

    inputs = [
        HandleInput(
            name="query_input",
            display_name="Query JSON",
            info="Parsed land query from LandIQ Parse Query",
            input_types=["Data", "Message"],
        ),
    ]

    outputs = [
        Output(display_name="Layer 1 Result", name="layer_1_result", method="layer_1_result"),
        Output(display_name="Layer 2 Result", name="layer_2_result", method="layer_2_result"),
        Output(display_name="Layer 3 Result", name="layer_3_result", method="layer_3_result"),
        Output(display_name="Layer 4 Result", name="layer_4_result", method="layer_4_result"),
        Output(display_name="Final Result", name="final_result", method="final_result"),
        Output(display_name="Final Message", name="final_message", method="final_message"),
    ]

    # ── Input parsing (unchanged) ───────────────────────────────────────

    def _parse_input(self) -> dict:
        raw = self.query_input
        if isinstance(raw, Data):
            if hasattr(raw, "data") and isinstance(raw.data, dict):
                return raw.data
            return json.loads(str(raw.get_text() if hasattr(raw, "get_text") else raw))
        if isinstance(raw, Message):
            return json.loads(raw.text)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            return json.loads(raw)
        return json.loads(str(raw))

    # ── Catalogue reading (unchanged) ───────────────────────────────────

    def _read_catalogue(self) -> list[dict]:
        catalogue = []
        if not os.path.isdir(AGENTS_DIR):
            self.log(f"agents_registry not found at {AGENTS_DIR}")
            return catalogue
        for folder_name in sorted(os.listdir(AGENTS_DIR)):
            folder_path = os.path.join(AGENTS_DIR, folder_name)
            if not os.path.isdir(folder_path):
                continue
            agent_file = None
            for fname in ["AGENT.md", "AGENT.txt", f"{folder_name}.md", f"{folder_name}.txt"]:
                fp = os.path.join(folder_path, fname)
                if os.path.isfile(fp):
                    agent_file = fp
                    break
            if not agent_file:
                for f in os.listdir(folder_path):
                    if f.endswith((".md", ".txt")):
                        agent_file = os.path.join(folder_path, f)
                        break
            if not agent_file:
                continue
            agent_info = self._parse_agent_file(agent_file, folder_name)
            if agent_info:
                catalogue.append(agent_info)
        self.log(f"Catalogue: {len(catalogue)} agents found")
        return catalogue

    def _parse_agent_file(self, filepath: str, fallback_name: str) -> dict | None:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None
        info = {"name": fallback_name, "description": "", "layer": 1}
        for line in content.split("\n"):
            line_stripped = line.strip()
            lower = line_stripped.lower()
            if lower.startswith("name:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val:
                    info["name"] = val
            elif lower.startswith("description:"):
                val = line_stripped.split(":", 1)[1].strip()
                if val:
                    info["description"] = val[:100]
            elif lower.startswith("layer:"):
                try:
                    info["layer"] = int(line_stripped.split(":", 1)[1].strip())
                except ValueError:
                    pass
        if not info["description"]:
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith(("#", "name:", "layer:", "---")):
                    info["description"] = line[:100]
                    break
        return info

    # ── LLM planning (unchanged) ────────────────────────────────────────

    def _plan_execution(self, query: dict, catalogue: list[dict]) -> dict:
        import requests
        agent_names = [a["name"] for a in catalogue]
        cat_text = "\n".join(
            f"- {a['name']} (layer {a['layer']}): {a['description']}"
            for a in sorted(catalogue, key=lambda x: x["layer"])
        )
        system_prompt = (
            "You are the ORCHESTRATOR of LandIQ — an Indian land investment advisor.\n"
            "You have FULL AUTHORITY to decide which agents run and in what order.\n\n"
            "Return ONLY this JSON (no markdown, no explanation):\n"
            '{"layers": [["agent1","agent2"], ["agent3"], ["agent4"]]}\n\n'
            "RULES:\n"
            "- Same list = parallel execution\n"
            "- Independent research agents (location, legal, financial, market, environmental) → early layers\n"
            "- Debate agents (bull, bear) need research results → middle layer\n"
            "- due_diligence needs everything → near end\n"
            "- senior_consultant ALWAYS last, alone\n"
            "- Only use agent names from the AVAILABLE AGENTS list\n"
            "- Return ONLY the JSON."
        )
        user_prompt = (
            f"AVAILABLE AGENTS:\n{cat_text}\n\n"
            f"ANALYSE: {query.get('land_size', '')} {query.get('land_unit', '')} "
            f"in {query.get('area', '')}, {query.get('city', '')}, {query.get('state', '')}. "
            f"Budget INR {query.get('total_budget', '')}. "
            f"Purpose: {query.get('purpose', '')}.\n\n"
            f"Return JSON plan now."
        )
        plan = self._call_llm_for_plan(system_prompt, user_prompt, agent_names)
        if plan:
            self.log(f"LLM PLAN: {plan['layers']}")
            return plan
        self.log("LLM planning failed — using catalogue layer numbers")
        return self._default_plan(catalogue)

    def _call_llm_for_plan(self, system: str, user: str, valid_names: list) -> dict | None:
        import requests
        env_path = os.path.join(PROJECT_ROOT, ".env")
        env_vars = {}
        if os.path.isfile(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        env_vars[k.strip()] = v.strip().strip('"').strip("'")
        groq_key = env_vars.get("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", ""))
        google_key = env_vars.get("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
        if groq_key:
            try:
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": env_vars.get("GROQ_MODEL", os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")),
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "temperature": 0.1, "max_tokens": 500,
                    },
                    timeout=30,
                )
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"]
                    text = text.strip().strip("`").strip()
                    if text.startswith("json"):
                        text = text[4:].strip()
                    plan_data = json.loads(text)
                    layers = [[a for a in layer if a in valid_names] for layer in plan_data.get("layers", [])]
                    layers = [l for l in layers if l]
                    if layers:
                        return {"layers": layers, "source": "llm"}
            except Exception as e:
                self.log(f"Groq failed: {str(e)[:80]}")
        if google_key:
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={google_key}",
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500},
                    },
                    timeout=30,
                )
                if r.status_code == 200:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    text = text.strip().strip("`").strip()
                    if text.startswith("json"):
                        text = text[4:].strip()
                    plan_data = json.loads(text)
                    layers = [[a for a in layer if a in valid_names] for layer in plan_data.get("layers", [])]
                    layers = [l for l in layers if l]
                    if layers:
                        return {"layers": layers, "source": "llm"}
            except Exception as e:
                self.log(f"Gemini failed: {str(e)[:80]}")
        return None

    def _default_plan(self, catalogue: list[dict]) -> dict:
        from collections import defaultdict
        layer_map = defaultdict(list)
        for a in catalogue:
            layer_map[a["layer"]].append(a["name"])
        layers = [layer_map[k] for k in sorted(layer_map.keys())]
        return {"layers": layers, "source": "default"}

    # ── Agent execution (unchanged) ─────────────────────────────────────

    def _run_agent(self, agent_name: str, state: dict) -> dict:
        import requests
        try:
            r = requests.post(
                f"{BACKEND_URL}/run-single-agent",
                json={"agent_name": agent_name, "state": state},
                timeout=120,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    return data.get("result", {})
                else:
                    return {"error_log": [f"{agent_name}: {data.get('error', 'unknown')}"]}
            else:
                return {"error_log": [f"{agent_name}: HTTP {r.status_code}"]}
        except Exception as e:
            return {"error_log": [f"{agent_name}: {str(e)[:80]}"]}

    def _run_layer(self, agent_names: list[str], state: dict) -> dict:
        combined = {}
        for i, name in enumerate(agent_names):
            if i > 0:
                time.sleep(0.5)
            self.log(f"  Running agent: {name}")
            result = self._run_agent(name, state)
            for k, v in result.items():
                if k in ("completed_agents", "error_log"):
                    combined[k] = combined.get(k, []) + (v if isinstance(v, list) else [v])
                else:
                    combined[k] = v
        return combined

    # ── Full pipeline (was `orchestrate()` — now also records per-layer data) ──

    def _run_full_pipeline(self) -> None:
        import requests
        self.log("=" * 50)
        self.log("LANGFLOW ORCHESTRATOR — Starting")
        self.log("=" * 50)

        self._layer_data = []  # [{layer_number, agents_in_layer, agent_outputs, time_taken}, ...]
        self._result = {"status": "run failed before completion"}

        try:
            query = self._parse_input()
        except Exception as e:
            self._result = {"error": f"Invalid input: {str(e)[:100]}"}
            return

        self.log(f"Query: {query.get('area', '?')}, {query.get('city', '?')}")
        state = dict(query)
        state.setdefault("completed_agents", [])
        state.setdefault("error_log", [])

        try:
            rag_q = f"{state.get('area', '')} {state.get('city', '')} {state.get('state', '')} {state.get('land_type', '')} land"
            r = requests.post(f"{BACKEND_URL}/rag-context", json={"query": rag_q}, timeout=30)
            if r.status_code == 200:
                state["rag_context"] = r.json().get("context", "")
                self.log("RAG context retrieved")
            else:
                state["rag_context"] = "No context available."
        except Exception:
            state["rag_context"] = "No context available."

        catalogue = self._read_catalogue()
        if not catalogue:
            self._result = {"error": "No agents found in agents_registry/"}
            return

        self.log("Planning execution...")
        plan = self._plan_execution(query, catalogue)
        self.log(f"Plan source: {plan['source']}")
        self.log(f"Layers: {plan['layers']}")

        total_start = time.time()
        for i, layer in enumerate(plan["layers"], 1):
            self.log(f"[Layer {i}] PLANNED: {', '.join(layer)}")
            self.log(f"[Layer {i}] RUNNING...")
            t0 = time.time()
            layer_result = self._run_layer(layer, state)
            elapsed = time.time() - t0
            self.log(f"[Layer {i}] COMPLETE in {elapsed:.1f}s")

            for k, v in layer_result.items():
                if k in ("completed_agents", "error_log"):
                    state[k] = state.get(k, []) + (v if isinstance(v, list) else [v])
                else:
                    state[k] = v

            agent_outputs = {name: state.get(f"{name}_output") for name in layer}
            layer_entry = {
                "layer_number": i,
                "agents_in_layer": list(layer),
                "agent_outputs": agent_outputs,
                "time_taken": round(elapsed, 1),
            }

            if i <= NUM_LAYER_OUTPUTS:
                self._layer_data.append(layer_entry)
            else:
                # More layers than canvas outputs (e.g. a 5th layer): fold
                # into the last output rather than silently dropping data.
                self.log(f"[Layer {i}] beyond the {NUM_LAYER_OUTPUTS} canvas layer outputs "
                         f"— merged into Layer {NUM_LAYER_OUTPUTS} Result")
                last = self._layer_data[NUM_LAYER_OUTPUTS - 1]
                last["agents_in_layer"] += list(layer)
                last["agent_outputs"].update(agent_outputs)
                last["time_taken"] = round(last["time_taken"] + elapsed, 1)

        total_time = time.time() - total_start

        if state.get("senior_consultant_output"):
            state["final_recommendation"] = state["senior_consultant_output"]
        state["orchestrator_source"] = "langflow"
        state["execution_plan"] = plan
        state["total_time_seconds"] = round(total_time, 1)

        self.log("=" * 50)
        self.log(f"DONE — plan={plan['source']} | agents={state.get('completed_agents', [])} | time={total_time:.1f}s")
        self.log("=" * 50)

        self._result = {k: v for k, v in state.items() if k != "rag_context"}

    def _ensure_run(self) -> None:
        """Runs the full orchestration exactly once per component execution;
        every output method calls this first and then just reads the cache."""
        if not getattr(self, "_ran", False):
            self._ran = True
            self._run_full_pipeline()

    def _layer_output(self, n: int) -> Data:
        self._ensure_run()
        layers = getattr(self, "_layer_data", [])
        if n <= len(layers):
            return Data(data=layers[n - 1])
        return Data(data={
            "layer_number": n,
            "agents_in_layer": [],
            "agent_outputs": {},
            "time_taken": 0,
            "note": f"No agents planned for layer {n} — the LLM plan only had {len(layers)} layer(s).",
        })

    # ── Public outputs ───────────────────────────────────────────────────

    def layer_1_result(self) -> Data:
        return self._layer_output(1)

    def layer_2_result(self) -> Data:
        return self._layer_output(2)

    def layer_3_result(self) -> Data:
        return self._layer_output(3)

    def layer_4_result(self) -> Data:
        return self._layer_output(4)

    def final_result(self) -> Data:
        self._ensure_run()
        return Data(data=self._result)

    def final_message(self) -> Message:
        self._ensure_run()
        return Message(text=json.dumps(self._result, default=str))
