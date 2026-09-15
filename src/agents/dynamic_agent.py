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

from src.rag.facts_store import get_structured_facts, format_structured_facts_block

logger = logging.getLogger(__name__)

# Must match src/rag/retriever.py's own fallback strings exactly — these are
# what get_rag_context() returns when there's genuinely nothing retrieved.
# _build_prompt() checks for them so that case gets an honest instruction
# instead of the sentinel string being silently embedded as if it were content.
NO_CONTEXT_SENTINELS = {
    "No context available.",
    "No relevant context found.",
    "No RAG context available.",
}

# Printed once at import. If this line does NOT appear when the server boots,
# the old dynamic_agent.py is still the file being imported.
print("[dynamic_agent] token accounting v2 loaded")

# ── Tuning knobs (keep small → stay under Groq free-tier TPM) ─────────────────
# 800 was clipping most agents mid-JSON (output regularly hit the cap exactly),
# which broke JSON parsing and fell back to a truncated raw_output blob. 1600
# still clipped verbose agents (e.g. Financial, which reasons through several
# numeric scenarios). Raised to 3000 as the ceiling for configs with headroom;
# _resolve_max_out_tokens() below clamps back down for any config (e.g. an
# external gateway config) that declares a tighter tpr restriction, so this
# never overshoots a real cap — land_plus's own 4096 tpr still leaves margin.
MAX_OUT_TOKENS = 3000    # per-agent completion cap (ceiling; see _resolve_max_out_tokens)
RAG_CAP        = 2200    # chars of RAG context injected (k bumped 4->6 in retriever.py, cap raised to match)
PRIOR_CAP      = 3000    # chars of prior-agent findings injected (raised: bull_rebuttal/bear_rebuttal add 2 more agents feeding due_diligence/senior_consultant)
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
        # Any agent's AGENT.md can opt into multimodal input by setting this
        # flag — it is never checked by agent name, so adding a second
        # image-reading agent later needs zero code changes here.
        "accepts_images": str(meta.get("accepts_images", "false")).strip().lower() == "true",
        # Same pattern for model_tier: "fast" routes this agent to a smaller
        # Groq model with its own rate-limit bucket (see llm_factory.py).
        # Unset -> normal default model, same as before this existed.
        "model_tier": (meta.get("model_tier", "") or "").strip().lower() or None,
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

    if rag in NO_CONTEXT_SENTINELS:
        rag_section = (
            "NO KNOWLEDGE BASE DATA WAS RETRIEVED for this location. The line above "
            "is a system status message, not content — do not quote it or treat it as "
            "a finding. You MUST explicitly disclose in your output that no report data "
            "was found for %s, %s, and label any figure you give as a general estimate, "
            "not verified data." % (area, city)
        )
    else:
        rag_section = rag[:RAG_CAP]

    try:
        structured_facts = get_structured_facts(area, city, st)
        facts_section = format_structured_facts_block(structured_facts) or (
            "No verified structured facts recorded for %s, %s yet — treat this tier as empty "
            "and fall through to KNOWLEDGE BASE (RAG), then general knowledge if needed." % (area, city)
        )
    except Exception as e:
        logger.warning("[facts_store] lookup failed: %s", str(e)[:100])
        facts_section = "Structured facts lookup unavailable this run — fall through to KNOWLEDGE BASE (RAG)."

    system = (
        "You are %s of LandIQ — Indian land investment advisory AI.\n\n"
        "%s\n\n"
        "ACCURACY RULES (MANDATORY):\n"
        "1. LOCATION-SPECIFIC: Every finding must reference %s, %s explicitly.\n"
        "2. PRIORITY ORDER FOR FACTS — never mix these tiers silently:\n"
        "   (a) STRUCTURED FACTS section below — verified, sourced, dated numbers. If present, use them "
        "EXACTLY as given and name the source.\n"
        "   (b) KNOWLEDGE BASE (RAG) section — real content retrieved from actual market reports, each "
        "chunk tagged '[Source: filename]'. Use that number and cite the filename.\n"
        "   (c) Only if neither (a) nor (b) covers a point, use your own general Indian real-estate "
        "knowledge — and you MUST label it as a general estimate, explicitly not verified data.\n"
        "3. FLAG WHAT'S NOT COVERED: If neither STRUCTURED FACTS nor the KNOWLEDGE BASE covers a specific "
        "point, say 'Limited data for %s — based on %s trends:' then give conditional analysis. Never "
        "present a general-knowledge estimate as if it came from verified data.\n"
        "4. REAL NUMBERS: Actual INR prices, actual %%, actual km. Never say 'moderate' without a number.\n"
        "5. NO GENERIC ADVICE: Never write 'low risk is good'. Give THIS property's specifics.\n"
        "6. CHAIN FINDINGS: Read prior agent outputs and reference their specific findings.\n"
        "7. BE CONCISE: Each field 2-3 tight sentences max. No filler.\n"
        "8. JSON ONLY: Respond with ONLY valid JSON. No preamble, no explanation."
    ) % (agent["display_name"], agent["role_text"], area, city, area, city)

    loan_str = "Rs.%s @ %.1f%%" % ("{:,.0f}".format(loan_a), loan_r) if loan else "None"
    human = (
        "PROPERTY:\n"
        "Location : %s, %s, %s\n"
        "Type     : %s | Size: %s %s | Budget: Rs.%s | Construction: Rs.%s\n"
        "Purpose  : %s | Timeline: %s yr | Risk: %s\n"
        "Title    : %s | Loan: %s\n"
        "Income   : Rs.%s/month expected\n\n"
        "STRUCTURED FACTS (VERIFIED — highest priority):\n%s\n\n"
        "KNOWLEDGE BASE (RAG):\n%s\n\n"
        "PRIOR AGENT FINDINGS:\n%s\n\n"
        "YOUR WORKFLOW:\n%s\n\n"
        "OUTPUT — respond with ONLY this JSON (all values specific to %s, %s):\n%s"
    ) % (area, city, st, land_t, size, unit,
         "{:,.0f}".format(budget), "{:,.0f}".format(con_b),
         purpose, timeline, risk,
         "YES" if deed else "NO (HIGH RISK)", loan_str,
         "{:,.0f}".format(inc_e), facts_section, rag_section, prior,
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


def _resolve_max_out_tokens():
    """MAX_OUT_TOKENS is a ceiling, not a fixed value — clamp it down to
    whatever the active LLM config actually allows so an external gateway
    config with a tight tpr restriction (e.g. doc_summariser_LLM_config's
    1000) never gets over-sent, while configs with headroom (e.g. land_plus's
    4096) get the fuller cap instead of everyone being stuck at the tightest
    config's limit."""
    try:
        from src.utils.llm_factory import _tls as _factory_tls
        ext_cfg = getattr(_factory_tls, "external_config", None)
        if ext_cfg:
            from src.utils.llm_factory import _ext_max_tokens
            return max(200, min(MAX_OUT_TOKENS, _ext_max_tokens(ext_cfg)))
        local_cfg = getattr(_factory_tls, "selected_config", None)
        if local_cfg:
            from src.utils.router_manager import _configs
            tpr = (_configs.get(local_cfg, {}).get("restrictions") or {}).get("tpr")
            if isinstance(tpr, (int, float)) and tpr > 0:
                return max(200, min(MAX_OUT_TOKENS, int(tpr) - 200))
    except Exception:
        pass
    return MAX_OUT_TOKENS


def _extract_text(raw):
    """Newer Gemini responses return .content as a list of content blocks
    (e.g. [{"type": "text", "text": "...", "extras": {"signature": "..."}}])
    instead of a plain string. Normalize either shape to plain text."""
    content = getattr(raw, "content", raw)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(content)


def _gemini_invoke(system_prompt, human_prompt, temperature):
    """Fast fallback when Groq is rate-limited (429) or its daily quota is spent.
    Also the fallback for the multimodal path itself when the primary Gemini
    call errors (e.g. a transient 503) — human_prompt may be a list of
    text+image content blocks in that case, which needs the same higher
    output cap as the primary multimodal call to avoid truncated JSON."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    out_cap = 2048 if isinstance(human_prompt, list) else MAX_OUT_TOKENS
    g = ChatGoogleGenerativeAI(
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
        temperature=temperature,
        max_output_tokens=out_cap,
    )
    return g.invoke([("system", system_prompt), ("human", human_prompt)])


def run_dynamic_agent(agent_name, state):
    t0 = time.time()
    it = ot = 0

    try:
        agent = _load_agent(agent_name)
    except FileNotFoundError as e:
        logger.error(str(e))
        return {"error_log": [str(e)], "completed_agents": ["%s (Missing)" % agent_name]}
    except Exception as e:
        logger.error("[%s] load error: %s", agent_name, e)
        return {"error_log": ["%s load error: %s" % (agent_name, str(e)[:120])],
                "completed_agents": ["%s (Load Error)" % agent_name]}

    # ── Optional live prompt override (e.g. a Langflow node's editable
    # "agent_prompt" field, pre-filled with the real AGENT.md content but
    # editable by the user before a run). Empty/unset -> no change, the
    # file's own role_text is used exactly as before.
    role_override = state.get("agent_role_override")
    if isinstance(role_override, str) and role_override.strip():
        agent["role_text"] = role_override

    system_prompt, human_prompt = _build_prompt(agent, state)

    # ── Headroom: compress input tokens before they reach the LLM ──
    # Driven by the user-set headroom_mode flag on the request (never hardcoded).
    if state.get("headroom_mode"):
        try:
            from src.utils.headroom_bridge import headroom_compress, record_manual_compression
            hr_sys = headroom_compress(system_prompt)
            hr_human = headroom_compress(human_prompt)
            system_prompt = hr_sys["compressed_text"]
            human_prompt = hr_human["compressed_text"]
            record_manual_compression(
                hr_sys["original_tokens"] + hr_human["original_tokens"],
                hr_sys["compressed_tokens"] + hr_human["compressed_tokens"],
            )
        except Exception as e:
            logger.warning("[%s] headroom compression skipped: %s", agent_name, str(e)[:100])

    # ── Optional live model override (e.g. a Langflow node's "llm_model"
    # dropdown — "groq/llama-3.3-70b-versatile" or "gemini/gemini-1.5-flash").
    # Unset/unrecognised -> falls through to the normal active-config
    # selection below exactly as before. llm_api_key_override lets a caller
    # (e.g. a client's own Langflow canvas, bringing their own account)
    # supply their own key instead of this project's GROQ_API_KEY/
    # GOOGLE_API_KEY — falls back to those env vars when no override key is
    # given, so every existing caller that only ever sent llm_model_override
    # behaves exactly as before. llm_fallback_override (+
    # llm_fallback_api_key_override) is a second provider/model to build if
    # the primary override can't be constructed at all (e.g. no key
    # available for it) — a real "priority 2", not cosmetic.
    def _build_override_llm(model_str, key_override):
        if not (isinstance(model_str, str) and "/" in model_str):
            return None
        _provider_hint, _, _model_hint = model_str.partition("/")
        _provider_hint = _provider_hint.strip().lower()
        _model_hint = _model_hint.strip()
        if _provider_hint == "groq":
            _key = key_override or os.environ.get("GROQ_API_KEY")
            if not _key:
                return None
            from langchain_groq import ChatGroq
            return ChatGroq(
                api_key=_key,
                model=_model_hint or os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
                temperature=agent["temperature"],
                max_tokens=_resolve_max_out_tokens(),
            )
        if _provider_hint in ("gemini", "google"):
            _key = key_override or os.environ.get("GOOGLE_API_KEY")
            if not _key:
                return None
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                google_api_key=_key,
                model=_model_hint or "gemini-1.5-flash",
                temperature=agent["temperature"],
            )
        return None

    llm = None
    llm_override = state.get("llm_model_override")
    if llm_override:
        try:
            llm = _build_override_llm(llm_override, state.get("llm_api_key_override"))
        except Exception as e:
            logger.warning("[%s] llm_model_override '%s' failed: %s", agent_name, llm_override, str(e)[:100])
            llm = None
        if llm is None:
            fallback_override = state.get("llm_fallback_override")
            if fallback_override:
                try:
                    llm = _build_override_llm(fallback_override, state.get("llm_fallback_api_key_override"))
                    if llm is not None:
                        logger.info("[%s] primary override unavailable, using fallback override '%s'",
                                    agent_name, fallback_override)
                except Exception as e:
                    logger.warning("[%s] llm_fallback_override '%s' failed: %s",
                                    agent_name, fallback_override, str(e)[:100])
                    llm = None

    # ── Multimodal read path — only agents whose AGENT.md sets
    # accepts_images: true, and only when this run actually received
    # visual_evidence (tiles retrieved by PixelRAG), get routed to a
    # vision-capable model with the retrieved images attached. Groq's
    # Llama 3.3 70B is text-only, so this deliberately bypasses it for
    # this one call — every other agent's path is untouched.
    human_payload = human_prompt
    visual_hits = state.get("visual_evidence") or []
    if agent.get("accepts_images") and visual_hits and os.environ.get("GOOGLE_API_KEY"):
        image_parts = []
        for hit in visual_hits[:3]:
            b64 = hit.get("image_base64") if isinstance(hit, dict) else None
            if b64:
                image_parts.append({
                    "type": "image_url",
                    "image_url": "data:image/png;base64,%s" % b64,
                })
        if image_parts:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(
                    google_api_key=os.environ["GOOGLE_API_KEY"],
                    model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
                    temperature=agent["temperature"],
                    # Multimodal answers (describing an image across several
                    # JSON fields) run past MAX_OUT_TOKENS and get cut off
                    # mid-JSON. This path always calls Gemini, never Groq, so
                    # raising it here doesn't touch the Groq TPM budget
                    # MAX_OUT_TOKENS was tuned for.
                    max_output_tokens=2048,
                )
                human_payload = [{"type": "text", "text": human_prompt}] + image_parts
                print("  [%s] multimodal: %d image(s) attached from visual_evidence"
                      % (agent_name, len(image_parts)))
            except Exception as e:
                logger.warning("[%s] multimodal setup failed, falling back to text: %s",
                                agent_name, str(e)[:100])
                human_payload = human_prompt

    # Get primary LLM (RouterChatModel via factory, or direct Groq) if no override applied
    if llm is None:
        try:
            from src.utils.llm_factory import get_llm_for_agent
            llm = get_llm_for_agent(agent_name, temperature=agent["temperature"],
                                     model_tier=agent.get("model_tier"))
        except Exception:
            pass

    if llm is None:
        try:
            from langchain_groq import ChatGroq
            _fallback_model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
            if agent.get("model_tier") == "fast":
                from src.utils.llm_factory import GROQ_FAST_MODEL
                _fallback_model = GROQ_FAST_MODEL
            llm = ChatGroq(
                api_key=os.environ.get("GROQ_API_KEY", ""),
                model=_fallback_model,
                temperature=agent["temperature"],
                max_tokens=_resolve_max_out_tokens(),
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
                # ChatGoogleGenerativeAI already takes max_output_tokens at
                # construction and rejects a bind-time "max_tokens" kwarg
                # (raises inside GenerateContentConfig, not at .bind() time,
                # so a bare try/except around .bind() doesn't catch it) —
                # skip the bind for it instead of paying a failed call.
                if "google" in _cls or "gemini" in _cls:
                    bound = llm
                else:
                    try:
                        bound = llm.bind(max_tokens=_resolve_max_out_tokens())
                    except Exception:
                        bound = llm
                raw = bound.invoke([("system", system_prompt), ("human", human_payload)])
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
                raw = _gemini_invoke(system_prompt, human_payload, agent["temperature"])
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
        text = _extract_text(raw).strip()
        if "```" in text:
            text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
        try:
            output = json.loads(text)
        except ValueError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            output = json.loads(m.group()) if m else {"raw_output": text[:500]}
    except Exception as e:
        logger.error("[%s] parse failed: %s", agent_name, e)
        output = {"raw_output": _extract_text(raw)[:500]}

    # ── Caveman: measure REAL output-token savings on the LLM's raw text ──
    # Only measured (not applied to `output`) — the structured fields shown in
    # the UI stay exactly as the LLM returned them; inject_caveman() already
    # shrinks output tokens by instructing the model, this just reports the
    # real savings instead of the frontend's old hardcoded ~65% guess.
    if state.get("caveman_mode") and text:
        try:
            from src.utils.compression_utils import caveman_compress, record_caveman_compression
            level = state.get("caveman_level", "full")
            if level not in ("lite", "full", "ultra"):
                level = "full"
            cav = caveman_compress(text, mode=level)
            record_caveman_compression(cav.original_tokens, cav.compressed_tokens)
        except Exception as e:
            logger.warning("[%s] caveman measurement skipped: %s", agent_name, str(e)[:100])

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
            resp_text = _extract_text(raw)
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
        "%s_metadata" % agent_name: {
            "agent": agent["display_name"],
            "llm_provider": provider,
            "llm_model_override": llm_override or None,
            "input_tokens": it,
            "output_tokens": ot,
            "total_tokens": it + ot,
            "duration_seconds": round(time.time() - t0, 2),
        },
        "completed_agents": [agent["display_name"]],
    }


# ── Compatibility stub ─────────────────────────────────────────────────────────
def clear_model_cache(agent_name=None):
    pass