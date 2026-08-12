# LandIQ Project — Briefing for Claude Code

## What this project is
LandIQ (folder: `ai_boardroom_v3`) is an AI-powered Indian land investment advisory platform. It's the core deliverable for Vedansh's GenAI internship at EY Gurugram, under mentor Sachin Gera ("sir"). Vedansh is a B.Tech ECE student with no prior coding background — built this largely with AI assistance. Sir evaluates by live demo and explicitly checks for: no hardcoding, dynamic agents, a real LLM orchestrator, runtime agent creation, and visible integration of a classmate's contributed components.

## People involved
- **Vedansh** — owner, non-technical background, needs clear/simple explanations.
- **Sachin Gera ("sir")** — mentor/evaluator. Checks demos strictly for hardcoding and fake/simulated integration.
- **Classmate** — built a DeBERTa LoRA-based PII detection model, `safety_guardrails.py`, and an external LLM configurator server (accessed via VS Code devtunnel on port 8001; configs include `sam_poorn`, `hello_llm`, `doc_summariser_LLM_config`).

## Current architecture (working, do not break)
- `api.py` (root, ~1350+ lines) — FastAPI backend, port 8000
- `src/graph/orchestrator_agent.py` — multi-agent orchestrator using LangGraph, LLM-planned execution layers
- `agents_registry/` — dynamic agents, each subfolder has `AGENT.md` + `SKILL.md`, loaded at runtime (not hardcoded)
- `src/utils/dynamic_agent.py` — universal agent runner
- ChromaDB — RAG pipeline
- MLflow / DagsHub — experiment tracking
- `guardrail_server.py` — port 8002, uses classmate's PII/guardrail components
- Classmate's LLM configurator — external server, devtunnel, port 8001

## Active work: Langflow integration
Adding Langflow (visual LLM workflow builder, port 7860) as an optional front-end layer.
- **Dual-path design**: `api.py` tries Langflow first, falls back automatically to local `orchestrator_agent.py` if Langflow is offline. This fallback must always work — it's a hard requirement.
- Key files: `src/utils/langflow_bridge.py`, `setup_langflow.py` (already run successfully; flow ID saved in `langflow_flow_id.txt`), `api_paste_block.py` (contains 3 new endpoints, needs to be pasted into `api.py` above the `if __name__ == "__main__":` line, around line ~1351 — **this step is not done yet**, causing `/langflow/status` to 404).
- Langflow runs in its own venv (`venv_langflow`), separate from the project's main `venv`. `python -m langflow` will fail if run inside the project venv — must be launched in its own terminal with its own environment activated.

## Hard rules — always follow
1. **Never break working components.** Every new integration must be additive with a safe fallback to the existing working path.
2. **No hardcoding, anywhere.** Agent names, configs, URLs, model selections — all must be dynamic/runtime-resolved. Sir checks for this specifically.
3. **Routes must be defined before `if __name__ == "__main__":`** in `api.py`. Anything placed after it never gets registered by FastAPI — this has caused repeated 404 bugs.
4. **Thread-local storage doesn't cross ThreadPoolExecutor boundaries.** If an LLM config is selected on the main thread, it must be explicitly passed into worker threads before spawning agents — don't rely on thread-local state alone.
5. **Groq free-tier limits are tight** (TPM + daily caps). Mitigate with: max 2 parallel workers, staggered starts, rate-limit-aware backoff, and a direct Groq fallback on every code path.
6. **Gemini needs `method="function_calling"`** in `with_structured_output()` when using AQ-prefix keys, or it throws 400 errors.
7. **Devtunnel URLs regenerate every VS Code session.** Don't assume a saved devtunnel URL from a previous session is still valid — verify before using.
8. **`doc_summariser_LLM_config` has a 1000 TPR cap.** Never send `max_tokens=4096` to it — causes 400 errors.
9. Prefer **Python patcher scripts** over PowerShell for editing HTML/JS — PowerShell misparses CSS `var(--x)` as a decrement operator.
10. **Always confirm the existing system still works before adding a new feature** — test the current state first, then build.

## Stack
Python, FastAPI, LangChain, LangGraph, LiteLLM Router, ChromaDB, MLflow, DagsHub, Groq (Llama 3.3 70B, primary), Gemini (fallback), Langflow 1.10.1. Windows + PowerShell + VS Code. Project path: `C:\Users\HP\OneDrive\Desktop\ai_boardroom_v3\`.

## What's next (as of this briefing)
1. Paste `api_paste_block.py` contents into `api.py` above `if __name__ == "__main__":` — verify `/langflow/status` returns correctly afterward.
2. Resolve GitHub secret-scanning block (a GCP API key was previously flagged) so pushes to `github.com/vedansh-5k/landiq` go through cleanly.
3. Confirm all agents still run with zero errors after Langflow integration is wired in.
4. Prepare a clear demo narrative for sir covering the new Langflow visual orchestration layer, explicitly showing it's real (not hardcoded) and that the fallback path works if Langflow is down.

## How to work with Vedansh
- Give complete, ready-to-run files or full scripts — not partial diffs or "find and replace this line" instructions.
- Give explicit, numbered steps in order — don't leave sequencing ambiguous.
- Keep explanations simple and practical; he's non-technical but demoing to a technical evaluator, so the underlying work still needs to be correct and defensible.
- Before adding anything new, verify the current system still works.
