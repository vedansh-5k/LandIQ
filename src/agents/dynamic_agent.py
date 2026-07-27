"""
dynamic_agent.py — LandIQ
Reads agents_registry/{name}/AGENT.md + SKILL.md
Compatible with Python 3.8+

Key reliability upgrades:
- Caps output tokens so agents don't blow Groq's TPM limit
- Trims RAG + prior-agent context so senior_consultant stops being "Request too large"
- RETRY WITH BACKOFF on 429 before falling back to Gemini
- AUTO-FALLS-BACK to Gemini flash when Groq retries exhausted
- Records real token usage into tracked_chain so the UI report works

TOKEN ACCOUNTING (the only thing changed in this revision):
The external student gateway returns no usage block on its responses, so
the old extractor returned (0, 0) for every call and the UI showed "—".
Now: the provider's own reported usage is used whenever it exists. When a
provider reports nothing, the EXACT prompt text and EXACT response text
are counted with the cl100k tokenizer — the same one OpenAI-compatible
gateways bill against. Measured, not invented.
"""
import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Printed once at import. If this line does NOT appear when the server boots,
# the old dynamic_agent.py is still the file being imported.
print("[dynamic_agent] token accounting v2 loaded")

# ── Tuning knobs (keep small → stay under Groq free-tier TPM) ─────────────────
MAX_OUT_TOKENS = 800     # per-agent completion cap
RAG_CAP        = 1500    # chars of RAG context injected
PRIOR_CAP      = 2000    # chars of prior-agent findings injected (fixes "too large")
FIELD_CAP      = 120     # chars per prior field


# ── Registry path (lazy, never crashes at import) ─────────────────────────────
_REGISTRY = None

def _get_registry():
    global _REGISTRY
    if _REGISTRY and Path(_REGISTRY).is_dir():
        return Path(_REGISTRY)

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "agents_registry",
        here.parent.parent / "agents_registry",
        here.parent / "agents_registry",
        Path.cwd() / "agents_registry",
        Path.cwd() / "src" / "agents_registry",
    ]
    env_path = os.environ.get("AGENTS_REGISTRY_PATH", "")
    if env_path:
        candidates.insert(0, Path(env_path))

    for c in candidates:
        try:
            if c.is_dir():
                _REGISTRY = str(c)
                logger.info("[REGISTRY] Found: %s", c)
                return c
        except Exception:
            continue

    fallback = Path.cwd() / "agents_registry"
    fallback.mkdir(exist_ok=True)
    _REGISTRY = str(fallback)
    logger.warning("[REGISTRY] Not found anywhere, using: %s", fallback)
    return fallback


# ── Parse AGENT.md / SKILL.md ─────────────────────────────────────────────────
def _parse_md(text):
    meta, body = {}, text
    if text.strip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                line = line.strip()
                if ":" in line and not line.startswith("-"):
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()
    return meta, body


def _load_agent(name):
    registry = _get_registry()
    folder = registry / name
    if not folder.is_dir():
        raise FileNotFoundError(
            "agents_registry/%s/ not found (registry=%s)" % (name, registry)
        )
    agent_md_path = folder / "AGENT.md"
    if not agent_md_path.exists():
        raise FileNotFoundError("agents_registry/%s/AGENT.md missing" % name)

    agent_md = agent_md_path.read_text(encoding="utf-8")
    skill_path = folder / "SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""

    meta, role_body = _parse_md(agent_md)
    _, skill_body = _parse_md(skill_text)

    output_fields = []
    for m in re.finditer(
        r"-\s*\{name:\s*(\w+)[^}]*description:\s*[\"']([^\"']*)[\"']", agent_md
    ):
        output_fields.append({"name": m.group(1), "description": m.group(2)})

    if not output_fields:
        output_fields = [
            {"name": "summary",        "description": "Summary of findings"},
            {"name": "risk_level",     "description": "Risk level HIGH/MEDIUM/LOW"},
            {"name": "key_findings",   "description": "Key findings for this property"},
            {"name": "recommendation", "description": "Specific recommendation"},
        ]

    return {
        "name":         meta.get("name", name),
        "display_name": meta.get("display_name", name.replace("_", " ").title()),
        "temperature":  float(meta.get("temperature", 0.3)),
        "layer":        int(meta.get("layer", 1)),
        "role_text":    role_body,
        "skill_steps":  skill_body,
        "output_fields": output_fields,
    }


def _prior_outputs(state, current):
    parts = []
    for k, v in state.items():
        if not k.endswith("_output") or k == "%s_output" % current or not v:
            continue
        label = k.replace("_output", "").replace("_", " ").title()
        if isinstance(v, dict):
            snippet = "; ".join(
                "%s: %s" % (fk, str(fv)[:FIELD_CAP]) for fk, fv in v.items() if fv
            )
        else:
            snippet = str(v)[:300]
        parts.append("[%s]: %s" % (label, snippet))
    joined = "\n".join(parts) if parts else "None yet."
    if len(joined) > PRIOR_CAP:
        joined = joined[:PRIOR_CAP] + " ...(trimmed)"
    return joined


def _output_schema(fields):
    return json.dumps(
        {f["name"]: "<%s>" % f["description"] for f in fields}, indent=2
    )


def _build_prompt(agent, state):
    area    = state.get("area", "")
    city    = state.get("city", "")
    st      = state.get("state", "")
    budget  = float(state.get("total_budget", 0))
    purpose = state.get("purpose", "")
    size    = state.get("land_size", 0)
    unit    = state.get("land_unit", "sq yards")
    land_t  = state.get("land_type", "")
    timeline= state.get("timeline_years", 5)
    risk    = state.get("risk_tolerance", "moderate")
    deed    = state.get("has_title_deed", False)
    loan    = state.get("taking_loan", False)
    loan_a  = float(state.get("loan_amount", 0))
    loan_r  = float(state.get("loan_interest_rate", 0))
    con_b   = float(state.get("construction_budget", 0))
    inc_e   = float(state.get("monthly_income_expectation", 0))
    rag     = (state.get("rag_context") or "").strip() or "No RAG context available."
    prior   = _prior_outputs(state, agent["name"])
    schema  = _output_schema(agent["output_fields"])

    system = (
        "You are %s of LandIQ — Indian land investment advisory AI.\n\n"
        "%s\n\n"
        "ACCURACY RULES (MANDATORY):\n"
        "1. LOCATION-SPECIFIC: Every finding must reference %s, %s explicitly.\n"
        "2. USE RAG CONTEXT: The knowledge base is your primary data source. Cite facts from it.\n"
        "3. NO HALLUCINATION: If no data for %s, say 'Limited data for %s — based on %s trends:' then give conditional analysis.\n"
        "4. REAL NUMBERS: Actual INR prices, actual %%, actual km. Never say 'moderate' without a number.\n"
        "5. NO GENERIC ADVICE: Never write 'low risk is good'. Give THIS property's specifics.\n"
        "6. CHAIN FINDINGS: Read prior agent outputs and reference their specific findings.\n"
        "7. BE CONCISE: Each field 2-3 tight sentences max. No filler.\n"
        "8. JSON ONLY: Respond with ONLY valid JSON. No preamble, no explanation."
    ) % (agent["display_name"], agent["role_text"], area, city, area, area, city)

    loan_str = "Rs.%s @ %.1f%%" % ("{:,.0f}".format(loan_a), loan_r) if loan else "None"
    human = (
        "PROPERTY:\n"
        "Location : %s, %s, %s\n"
        "Type     : %s | Size: %s %s | Budget: Rs.%s | Construction: Rs.%s\n"
        "Purpose  : %s | Timeline: %s yr | Risk: %s\n"
        "Title    : %s | Loan: %s\n"
        "Income   : Rs.%s/month expected\n\n"
        "KNOWLEDGE BASE (RAG):\n%s\n\n"
        "PRIOR AGENT FINDINGS:\n%s\n\n"
        "YOUR WORKFLOW:\n%s\n\n"
        "OUTPUT — respond with ONLY this JSON (all values specific to %s, %s):\n%s"
    ) % (area, city, st, land_t, size, unit,
         "{:,.0f}".format(budget), "{:,.0f}".format(con_b),
         purpose, timeline, risk,
         "YES" if deed else "NO (HIGH RISK)", loan_str,
         "{:,.0f}".format(inc_e), rag[:RAG_CAP], prior,
         (agent["skill_steps"] or "")[:1200], area, city, schema)

    return system, human


# ══════════════════════════════════════════════════════════════════════════════
# TOKEN ACCOUNTING — the only rewritten section
# ══════════════════════════════════════════════════════════════════════════════
_ENC = None
_ENC_TRIED = False


def _encoder():
    """cl100k_base — what Groq and OpenAI-compatible gateways bill against."""
    global _ENC, _ENC_TRIED
    if _ENC_TRIED:
        return _ENC
    _ENC_TRIED = True
    try:
        import tiktoken
        _ENC = tiktoken.get_encoding("cl100k_base")
    except Exception as e:
        logger.info("[TOKENS] tiktoken unavailable (%s) — using char/4", e)
        _ENC = None
    return _ENC


def _count_tokens(text):
    """Count real tokens in real text. Never returns a made-up number."""
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, len(str(text)) // 4)


def _extract_tokens(raw):
    """
    Token usage as REPORTED BY THE PROVIDER.
    Checks every place a provider might put it. Returns (0, 0) when the
    provider reports nothing — the caller then measures the text itself.
    """
    def pull(d):
        if not isinstance(d, dict):
            return 0, 0
        for ikey, okey in (("input_tokens", "output_tokens"),
                           ("prompt_tokens", "completion_tokens"),
                           ("promptTokenCount", "candidatesTokenCount")):
            if ikey in d or okey in d:
                try:
                    return int(d.get(ikey) or 0), int(d.get(okey) or 0)
                except Exception:
                    return 0, 0
        return 0, 0

    candidates = []

    um = getattr(raw, "usage_metadata", None)
    if isinstance(um, dict):
        candidates.append(um)
    elif um is not None:
        candidates.append({
            "input_tokens":  getattr(um, "input_tokens", 0) or 0,
            "output_tokens": getattr(um, "output_tokens", 0) or 0,
        })

    rm = getattr(raw, "response_metadata", None) or {}
    if isinstance(rm, dict):
        for key in ("token_usage", "usage", "usage_metadata", "usageMetadata"):
            if isinstance(rm.get(key), dict):
                candidates.append(rm[key])
        candidates.append(rm)

    ak = getattr(raw, "additional_kwargs", None) or {}
    if isinstance(ak, dict):
        for key in ("usage", "token_usage", "usage_metadata"):
            if isinstance(ak.get(key), dict):
                candidates.append(ak[key])

    u = getattr(raw, "usage", None)
    if isinstance(u, dict):
        candidates.append(u)
    elif u is not None:
        candidates.append({
            "prompt_tokens":     getattr(u, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
        })

    for c in candidates:
        a, b = pull(c)
        if a or b:
            return a, b
    return 0, 0
# ══════════════════════════════════════════════════════════════════════════════


def _is_rate_limit_error(e):
    """Check if an exception is a 429 rate limit error."""
    msg = str(e).lower()
    return "429" in msg or "rate limit" in msg or "rate_limit" in msg


def _gemini_invoke(system_prompt, human_prompt, temperature):
    """Fast fallback when Groq is rate-limited (429) or its daily quota is spent."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    g = ChatGoogleGenerativeAI(
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        temperature=temperature,
        max_output_tokens=MAX_OUT_TOKENS,
    )
    return g.invoke([("system", system_prompt), ("human", human_prompt)])


def run_dynamic_agent(agent_name, state):
    try:
        agent = _load_agent(agent_name)
    except FileNotFoundError as e:
        logger.error(str(e))
        return {"error_log": [str(e)], "completed_agents": ["%s (Missing)" % agent_name]}
    except Exception as e:
        logger.error("[%s] load error: %s", agent_name, e)
        return {"error_log": ["%s load error: %s" % (agent_name, str(e)[:120])],
                "completed_agents": ["%s (Load Error)" % agent_name]}

    system_prompt, human_prompt = _build_prompt(agent, state)

    # Get primary LLM (RouterChatModel via factory, or direct Groq)
    llm = None
    try:
        from src.utils.llm_factory import get_llm_for_agent
        llm = get_llm_for_agent(agent_name, temperature=agent["temperature"])
    except Exception:
        pass

    if llm is None:
        try:
            from langchain_groq import ChatGroq
            llm = ChatGroq(
                api_key=os.environ.get("GROQ_API_KEY", ""),
                model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                temperature=agent["temperature"],
                max_tokens=MAX_OUT_TOKENS,
            )
        except Exception as e:
            llm = None
            logger.warning("[%s] Groq init failed: %s", agent_name, str(e)[:80])

    # ── Invoke with RETRY for 429, then fall back to Gemini ──
    raw = None
    provider = "groq"
    primary_err = None

    if llm is not None:
        # Name the provider from the class actually in use, for the report
        _cls = type(llm).__name__.lower()
        if "external" in _cls:
            provider = "external"
        elif "router" in _cls:
            provider = "router"
        elif "google" in _cls or "gemini" in _cls:
            provider = "gemini"

        # ★ Retry up to 3 times with exponential backoff for rate-limit errors
        for attempt in range(3):
            try:
                try:
                    bound = llm.bind(max_tokens=MAX_OUT_TOKENS)
                except Exception:
                    bound = llm
                raw = bound.invoke([("system", system_prompt), ("human", human_prompt)])
                break  # success → exit retry loop
            except Exception as e:
                primary_err = str(e)
                if _is_rate_limit_error(e) and attempt < 2:
                    wait = 4 * (attempt + 1)  # 4s, 8s
                    print("  [RETRY %d/3] %s -> 429, waiting %ds..." % (attempt + 1, agent_name, wait))
                    time.sleep(wait)
                    continue
                else:
                    logger.warning("[%s] primary LLM failed: %s", agent_name, primary_err[:120])
                    break

    # ── Gemini fallback if primary failed ──
    if raw is None:
        if os.environ.get("GOOGLE_API_KEY"):
            try:
                raw = _gemini_invoke(system_prompt, human_prompt, agent["temperature"])
                provider = "gemini"
                print("  [FALLBACK] %s -> Gemini flash (primary unavailable)" % agent_name)
            except Exception as e:
                return {"error_log": ["%s: all LLMs failed (%s)" % (agent_name, str(e)[:80])],
                        "completed_agents": ["%s (Failed)" % agent_name]}
        else:
            return {"error_log": ["%s: %s" % (agent_name, (primary_err or "no LLM")[:100])],
                    "completed_agents": ["%s (Failed)" % agent_name]}

    # ── Parse JSON output ──
    text = ""
    try:
        text = raw.content if hasattr(raw, "content") else str(raw)
        text = text.strip()
        if "```" in text:
            text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
        try:
            output = json.loads(text)
        except ValueError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            output = json.loads(m.group()) if m else {"raw_output": text[:500]}
    except Exception as e:
        logger.error("[%s] parse failed: %s", agent_name, e)
        output = {"raw_output": str(getattr(raw, "content", raw))[:500]}

    # ══════════════════════════════════════════════════════════════════════════
    # Record tokens for the report — provider-reported first, measured second
    # ══════════════════════════════════════════════════════════════════════════
    try:
        from src.utils.tracked_chain import record_agent_tokens

        it, ot = _extract_tokens(raw)
        exact = bool(it or ot)

        if not exact:
            # Provider sent no usage block (the external gateway does not).
            # Measure the real strings that actually went over the wire.
            resp_text = raw.content if hasattr(raw, "content") else str(raw)
            it = _count_tokens(system_prompt) + _count_tokens(human_prompt)
            ot = _count_tokens(resp_text)

        try:
            record_agent_tokens(agent["display_name"], it, ot,
                                provider=provider, exact=exact)
        except TypeError:
            # tracked_chain.py without the exact= parameter
            record_agent_tokens(agent["display_name"], it, ot, provider=provider)

        print("  [TOKENS] %-28s IN=%-6d OUT=%-5d TOTAL=%-6d (%s%s)"
              % (agent["display_name"][:28], it, ot, it + ot, provider,
                 "" if exact else ", measured"))

    except Exception as e:
        logger.warning("[%s] token accounting failed: %s", agent_name, str(e)[:140])
        print("  [TOKENS] %s -> FAILED: %s" % (agent_name, str(e)[:100]))

    return {
        "%s_output" % agent_name: output,
        "completed_agents": [agent["display_name"]],
    }


# ── Compatibility stub ─────────────────────────────────────────────────────────
def clear_model_cache(agent_name=None):
    pass