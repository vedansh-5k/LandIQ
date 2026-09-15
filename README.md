# LandIQ — Multi-Agent AI Advisory Platform for Indian Land Investment

LandIQ analyses a specific land or property purchase in India and returns a structured
investment recommendation — location intelligence, legal/title risk, financial ROI,
market timing, environmental risk, a bull-vs-bear debate with rebuttals, independent
due diligence, and a final consultant verdict.

It is built as a **real multi-agent system**: 13 specialist agents defined as editable
Markdown files, an LLM that plans their execution order at runtime, a retrieval layer
grounded in actual Indian market-research reports, and a configurable LLM routing
layer so any agent can be pointed at any model provider without touching code.

---

## Table of contents

- [Why this is not a prompt wrapper](#why-this-is-not-a-prompt-wrapper)
- [Architecture](#architecture)
- [The 13 agents](#the-13-agents)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [How a request flows](#how-a-request-flows)
- [The two-tier LLM config system](#the-two-tier-llm-config-system)
- [RAG grounding](#rag-grounding)
- [Safety guardrails](#safety-guardrails)
- [Langflow visual layer](#langflow-visual-layer)
- [API reference](#api-reference)
- [Project layout](#project-layout)
- [Current status and known limitations](#current-status-and-known-limitations)
- [Tech stack](#tech-stack)

---

## Why this is not a prompt wrapper

Four design decisions do the heavy lifting:

**1. Agents are data, not code.** Each agent lives in `agents_registry/<name>/` as an
`AGENT.md` (role, output schema, temperature, execution layer) plus an optional
`SKILL.md` (step-by-step workflow). `src/agents/dynamic_agent.py` is a single universal
runner that reads those files at request time. Adding a fourteenth agent means adding a
folder — no Python changes, no redeploy, no registry edit.

**2. Execution order is planned by an LLM, not hardcoded.** `src/graph/orchestrator_agent.py`
asks a model which agents are relevant to this specific query and how to layer them into
dependency tiers, then executes those tiers with a thread pool. The response reports
`execution_plan.source` as `"llm"` when the planner ran, or `"default"` when it fell back —
so you can always tell which path produced a given result.

**3. Agents chain on each other's findings.** Layer 2 agents receive Layer 1 outputs in
their prompts. The Bull and Bear agents argue a case; their *rebuttal* counterparts then
receive the opposing argument and attack it specifically. Due Diligence receives all prior
outputs and hunts for contradictions between them.

**4. Model choice is runtime configuration.** An LLM "config" (a priority chain of
models with rate limits) is created through the API or UI and stored in
`configs/*.json` + SQLite. Any agent can be bound to any config at runtime. Nothing about
which model runs which agent is compiled in.

---

## Architecture

```
                        Browser / API client
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │   FastAPI backend  :8000     │
                  │          api.py              │
                  └───────────────┬──────────────┘
                                  │
              ┌───────────────────┴───────────────────┐
              ▼                                       ▼
   ┌──────────────────────┐              ┌──────────────────────┐
   │  Orchestrator        │              │  LLM Config Router   │
   │  (LangGraph)         │              │  (LiteLLM)           │
   │                      │              │                      │
   │  LLM plans layers    │              │  priority chain      │
   │  runs agents/layer   │              │  + auto failover     │
   └──────────┬───────────┘              └──────────┬───────────┘
              │                                     │
              ▼                            ┌────────┴────────┐
   ┌──────────────────────┐                ▼                 ▼
   │  dynamic_agent.py    │              Groq            Gemini
   │  reads               │            (primary)         (fallback)
   │  agents_registry/    │
   └──────────┬───────────┘
              │  grounding
     ┌────────┼─────────────────┐
     ▼        ▼                 ▼
 ChromaDB  Structured facts  PixelRAG :30001
 RAG       data/land_facts/  (charts & tables)


 Side services:  Guardrail :8002 (DeBERTa PII)  ·  Langflow :7860 (visual)
```

---

## The 13 agents

| Agent | Layer | Role |
|---|---|---|
| `location` | 1 | Connectivity, infrastructure, price range, appreciation potential |
| `legal` | 1 | Title risk, RERA status, CLU requirement, encumbrances, state law |
| `financial` | 1 | Acquisition cost, stamp duty, ROI, appreciation, breakeven |
| `market` | 1 | Market phase, demand/supply, price momentum, buyer profile, timing |
| `environmental_risk` | 1 | Flood risk, pollution, environmental score |
| `visual_document` | 1 | Reads charts/tables from market-report PDFs (vision model) |
| `area_crowd` | 2 | Resident/worker demographic profile of the locality |
| `bull` | 2 | Best-case thesis: upside triggers, catalyst timeline |
| `bear` | 2 | Worst-case thesis: downside risks, liquidity, macro |
| `bull_rebuttal` | 3 | Attacks the bear case point by point |
| `bear_rebuttal` | 3 | Attacks the bull case point by point |
| `due_diligence` | 4 | Cross-checks every agent, flags contradictions, verification checklist |
| `senior_consultant` | 5 | Final BUY/HOLD/AVOID verdict, offer price, non-negotiable conditions |

Each agent declares its own `layer:` in its `AGENT.md`. The orchestrator reads those
values — the table above is a description of current data, not a hardcoded sequence.

---

## Quick start

**Prerequisites:** Python 3.10+, Windows or Linux, a Groq API key (free tier works).

```bash
git clone https://github.com/vedansh-5k/LandIQ.git
cd LandIQ

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

copy .env.example .env         # Windows   (cp on macOS/Linux)
# then edit .env and add your API keys
```

**Run everything with one command:**

```bash
python run.py
```

`run.py` starts each service in its own window, in order, waiting for each to respond
before starting the next (they contend for the same on-disk locks if started together):

| Service | Port | Purpose |
|---|---|---|
| LandIQ backend | 8000 | Main API + web UI |
| Guardrail server | 8002 | DeBERTa PII detection / safety |
| Langflow | 7860 | Visual workflow builder (optional) |
| PixelRAG | 30001 | Visual document search (optional) |

Then open **http://localhost:8000**.

**Run just the backend:**

```bash
python -m uvicorn api:app --port 8000
```

---

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | **yes** | Primary LLM provider |
| `GOOGLE_API_KEY` | recommended | Gemini fallback when Groq is rate-limited |
| `GROQ_MODEL` | no | Default Groq model (default: `openai/gpt-oss-120b`) |
| `GEMINI_MODEL` | no | Default Gemini model (default: `gemini-flash-latest`) |
| `OPENROUTER_API_KEY` | no | Additional provider option |
| `CLOUDFLARE_ACCOUNT_ID` | no | For the Llama-Vision reader used by PixelRAG |
| `CLOUDFLARE_API_TOKEN` | no | As above |
| `ENCRYPTION_KEY` | no | Encrypts stored provider credentials |

Never commit `.env` — it is gitignored.

---

## How a request flows

1. **`POST /analyse`** receives the property details (area, city, state, size, budget,
   purpose, timeline, risk tolerance, title status, loan details).
2. The **orchestrator** asks an LLM which agents matter for this query and how to layer them.
3. For each layer, agents run **concurrently** (capped at 2 workers to respect Groq's
   free-tier rate limits), with staggered starts and backoff on 429s.
4. Before each agent runs, `dynamic_agent.py` assembles its prompt from:
   - the agent's own `AGENT.md` role + `SKILL.md` workflow,
   - **structured facts** (verified, sourced numbers) if any exist for that locality,
   - **RAG context** retrieved from indexed market reports,
   - **prior agents' outputs** (so later agents can reference earlier findings),
   - optional **visual evidence** from PixelRAG for vision-capable agents.
5. The prompt enforces a strict fact hierarchy: verified structured facts first, then
   cited RAG content, then general knowledge — and general knowledge **must** be labelled
   as an unverified estimate in the output.
6. Every call's real token usage is recorded (provider-reported when available, otherwise
   measured with the `cl100k` tokenizer — never estimated).
7. The final state is assembled into a structured JSON response and rendered in the UI.

---

## The two-tier LLM config system

**Config 1 — the model pool.** An LLM config is a named priority chain, e.g.

```json
{
  "usecase_name": "landiq",
  "config_name": "model",
  "operations": {
    "chat": [
      { "litellm_model": "groq/openai/gpt-oss-120b",  "priority": 1 },
      { "litellm_model": "groq/openai/gpt-oss-20b",   "priority": 2 },
      { "litellm_model": "gemini/gemini-flash-latest","priority": 3 }
    ]
  },
  "restrictions": { "tpm": 100000, "rpm": 60, "tpr": 4096 }
}
```

Priority 2 is used when priority 1 fails or is rate-limited, and so on. Configs are
created via `POST /configs` (or the web UI) and stored in `configs/*.json` + SQLite.

**Config 2 — the agent binding.** `POST /agent-config/{agent}/set-llm-config` binds one
agent to one config. At run time `src/utils/llm_factory.py` resolves, in order:
a run-level override → the agent's own binding → the global active config → a direct
Groq fallback. This is how different agents can run on different models simultaneously.

Both tiers are also exposed as boxes on the Langflow canvas (see below).

---

## RAG grounding

Two independent grounding layers, deliberately ranked:

**Structured facts** (`data/land_facts/`) — hand-verified, sourced, dated numbers stored
as JSON per locality. Highest priority; if a fact exists here, the agent must use it and
name the source. Adding a locality means adding a file.

**Vector retrieval** (ChromaDB) — semantic search across indexed Indian market-research
reports. Each retrieved chunk is tagged `[Source: filename]` so the agent can cite it.

If neither covers a point, the agent is required to say so explicitly and label its answer
as a general estimate rather than presenting it as verified data.

> **Note on source documents:** the PDFs used to build the index (Knight Frank,
> Magicbricks, ANAROCK, Savills research publications) are third-party copyrighted
> material and are **not redistributed in this repository**. Place your own reports in
> `data/land_reports/` and run the ingestion pipeline to build your index.

---

## Safety guardrails

A separate service on port 8002 wraps a **DeBERTa LoRA fine-tuned PII detection model**
(contributed by a project collaborator) plus rule-based safety filters. It covers PII
masking, harmful content, jailbreak attempts, prompt injection, and toxicity. The model
weights live in `models/finetuned-deberta/` (gitignored — supply your own or the
collaborator's adapter).

Check it with `GET http://localhost:8002/health`.

---

## Langflow visual layer

Langflow (port 7860) provides an optional visual representation of the system: every
agent, the layer ordering, and the LLM config boxes are visible and inspectable on a
canvas.

`api.py` follows a **dual-path design**: it can route an analysis through Langflow, and
falls back automatically to the local orchestrator if Langflow is unavailable. The local
orchestrator is always the authoritative path.

On the canvas, `LandIQ Config: <name>` boxes (one per active config, regenerated from the
live config list by `sync_config1_boxes.py`) wire into `LandIQ Config Agent`, which binds
the chosen config to a chosen agent and runs it for real against the backend.

Regenerate the config boxes after adding or removing a config on the website:

```bash
python sync_config1_boxes.py
```

---

## API reference

Interactive docs: **http://localhost:8000/docs**

**Analysis**
- `POST /analyse` — run the full multi-agent analysis
- `POST /run-single-agent` — run one agent in isolation

**LLM configs (Config 1)**
- `GET /configs` · `GET /configs/active` — list configs
- `POST /configs` — create a config
- `PUT /configs/{full_name}` · `DELETE /configs/{full_name}`
- `POST /configs/{full_name}/enable` · `/disable`
- `POST /test/{full_name}` — send a live test prompt through a config

**Agent bindings (Config 2)**
- `GET /agent-config` — current bindings
- `POST /agent-config/{agent}/set-llm-config` · `/clear-llm-config`

**Agents**
- `GET /agents` · `GET /agents/{name}` — list/read agent definitions
- `POST /agents` — create an agent at runtime
- `POST /agents/create` — generate an agent from a URL or uploaded file

**Ops**
- `GET /health` — service health + active configs
- `GET /logs` · `GET /logs/{full_name}` — usage logs
- `GET /langflow/status` — Langflow wiring status

---

## Project layout

```
api.py                      FastAPI backend — all HTTP endpoints
run.py                      One-command launcher for every service
guardrail_server.py         PII / safety service (port 8002)
sync_config1_boxes.py       Regenerates Langflow config boxes from live configs

agents_registry/            One folder per agent (AGENT.md + SKILL.md)
  location/  legal/  financial/  market/  bull/  bear/
  bull_rebuttal/  bear_rebuttal/  due_diligence/
  senior_consultant/  environmental_risk/  visual_document/  area_crowd/

src/
  agents/dynamic_agent.py   Universal agent runner (reads agents_registry/)
  graph/orchestrator_agent.py   LLM-planned multi-agent execution
  rag/                      ChromaDB retrieval + structured facts store
  utils/
    llm_factory.py          Model resolution: override → binding → active → fallback
    config_store.py         LLM config persistence
    router_manager.py       LiteLLM router construction per config
    agent_configurator.py   Per-agent settings and config bindings
    langflow_bridge.py      Langflow integration + automatic fallback
    pixelrag_bridge.py      Visual document search client
  langflow/                 Custom Langflow component source

configs/                    Saved LLM configs (JSON)
data/land_facts/            Verified structured facts per locality
frontend/                   Web UI
```

---

## Current status and known limitations

Documented honestly rather than discovered in a demo.

**Working and verified end to end**
- Full 13-agent pipeline via the local orchestrator — verified with real runs
  (25 LLM calls, ~61k tokens, LLM-generated execution plan, zero errors).
- Dynamic agent loading, RAG retrieval, structured facts, guardrail service,
  LLM config system, per-agent config binding, PixelRAG bridge.
- Langflow `LandIQ Config: <name>` → `LandIQ Config Agent` path — runs real agents
  against a chosen config and returns genuine results.

**Known limitations**

1. **Langflow dropdown selections are not honoured at run time.** In this Langflow
   version, a custom component's dropdown value is re-derived from the component's own
   code on every run rather than read from the saved selection, so a user's pick is
   discarded. Verified across ten independent tests including fresh nodes and direct
   UI interaction. The config boxes therefore use **explicit wiring** (connect the box
   for the config you want) instead of a dropdown — same result, reliable delivery.

2. **The Langflow full-pipeline canvas does not read live query input.** The eleven
   per-agent input boxes on the canvas hold static values from an earlier test and have
   no incoming connections, so the visual pipeline analyses that fixed property rather
   than a submitted query. **Use the local orchestrator (`POST /analyse`) for real
   analysis**; treat the Langflow canvas as an architecture visualisation until those
   inputs are wired.

3. **MLflow / DagsHub tracking is non-functional.** `log_analysis_run()` is invoked with
   one argument but defined to take three, and `init_mlflow()` is never called — so runs
   are never logged. The code is present but inert; the dashboard will be empty.

4. **Groq free-tier rate limits** constrain throughput. Mitigated with 2 parallel workers,
   staggered starts, exponential backoff on 429, and automatic Gemini fallback.

---

## Tech stack

**Backend** FastAPI · Uvicorn · Pydantic
**AI orchestration** LangChain · LangGraph · LiteLLM Router
**Models** Groq (primary) · Google Gemini (fallback) · Cloudflare Llama-Vision (visual)
**Retrieval** ChromaDB · SentenceTransformers · PixelRAG
**Safety** DeBERTa (LoRA fine-tuned) PII detection
**Visual layer** Langflow 1.10.1
**Tracking** MLflow / DagsHub *(see limitations)*

---

## License & attribution

Built as a GenAI internship project. The DeBERTa PII guardrail model and the external
LLM configurator service were contributed by a project collaborator. Market-research
PDFs used for RAG grounding are third-party copyrighted publications and are not
included in this repository.
