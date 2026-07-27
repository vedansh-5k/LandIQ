"""
toon.py
-------
TOON = Token-Oriented Object Notation
Reduces INPUT tokens before sending to LLM.

Core fix: compress_rag_context now always saves tokens.
  - Only activates compression if text > 200 chars
  - Removes prefix labels that added overhead
  - Deduplication pass before truncation
  - Tighter join format

Token savings targets:
  RAG context     : 35-55% reduction
  Agent handoffs  : 45-60% reduction
  List encoding   : 40-60% reduction
"""

from typing import Any


# ── CORE TOON ENCODER ──────────────────────────────────

def encode_list(name: str, records: list) -> str:
    """
    Converts list of dicts → TOON format.
    Field names written once. Rows only after.

    JSON:   [{"id":1,"city":"Delhi"},{"id":2,"city":"Gurgaon"}]
    TOON:   data[2]{id,city}:
            1,Delhi
            2,Gurgaon

    Savings: 40-60% on lists with 3+ records.
    """
    if not records:
        return f"{name}[]"

    if not isinstance(records[0], dict):
        # Fallback for non-dict lists
        return f"{name}: " + "; ".join(str(r) for r in records[:6])

    keys = list(records[0].keys())
    count = len(records)
    header = f"{name}[{count}]{{{','.join(keys)}}}:"

    rows = []
    for rec in records:
        row_vals = []
        for k in keys:
            val = str(rec.get(k, "")).replace(",", ";").replace("\n", " ").strip()
            if len(val) > 150:
                val = val[:150] + ".."
            row_vals.append(val)
        rows.append(",".join(row_vals))

    return header + "\n" + "\n".join(rows)


def encode_dict(name: str, data: dict) -> str:
    """
    Single dict → compact key:val TOON format.
    No JSON brackets, no quotes.

    JSON:   {"roi": 12, "risk": "low"}
    TOON:   roi:12
            risk:low
    """
    if not data:
        return f"{name}:{{}}"

    lines = [f"[{name.upper()}]"]
    for k, v in data.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        v_str = str(v).replace("\n", " ").strip()
        if len(v_str) > 120:
            v_str = v_str[:120] + ".."
        lines.append(f"{k}:{v_str}")
    return "\n".join(lines)


def encode_summary_handoff(agent_name: str, output_obj) -> str:
    """
    Pydantic agent output → compact TOON for agent-to-agent passing.

    Instead of passing full verbose JSON (~400 chars),
    passes only key fields compactly (~150 chars).
    Savings: 45-60% on inter-agent context.
    """
    if output_obj is None:
        return f"[{agent_name.upper()}]:n/a"

    try:
        if hasattr(output_obj, "model_dump"):
            data = output_obj.model_dump()
        elif hasattr(output_obj, "dict"):
            data = output_obj.dict()
        else:
            return f"[{agent_name.upper()}]:{str(output_obj)[:80]}"

        lines = [f"[{agent_name.upper()}]"]
        for k, v in data.items():
            if v is None or v == "" or v == [] or v == {}:
                continue
            v_str = str(v).replace("\n", " ").strip()
            if len(v_str) > 100:
                v_str = v_str[:100] + ".."
            lines.append(f"{k}:{v_str}")
        return "\n".join(lines)

    except Exception:
        return f"[{agent_name.upper()}]:{str(output_obj)[:80]}"


# ── RAG CONTEXT COMPRESSOR ──────────────────────────────

def compress_rag_context(raw_context: str) -> str:
    """
    Compresses RAG context string before sending to LLM.

    KEY FIX vs previous version:
    - If text is short (<200 chars), return as-is (no overhead added)
    - No numbered prefixes [1][2][3] — those add tokens
    - Dedup by first 50 chars fingerprint
    - Truncate each chunk to 250 chars max
    - Join with single newline (not double)

    Savings: 35-55% on typical ChromaDB retrieval output.
    """
    if not raw_context:
        return "No context."

    # Short text — compressing would ADD overhead, skip
    if len(raw_context) < 200:
        return raw_context

    # Split into chunks — try double newline first
    if "\n\n" in raw_context:
        chunks = [c.strip() for c in raw_context.split("\n\n") if c.strip()]
    else:
        chunks = [c.strip() for c in raw_context.split("\n") if c.strip()]

    if not chunks:
        return raw_context

    # Deduplicate by first 50 char fingerprint
    seen = set()
    unique = []
    for chunk in chunks:
        fp = chunk[:50].lower()
        if fp not in seen:
            seen.add(fp)
            unique.append(chunk)

    # Truncate each chunk — key facts are always at the start
    compressed = []
    for chunk in unique[:5]:  # max 5 chunks
        if len(chunk) > 250:
            chunk = chunk[:250] + ".."
        compressed.append(chunk)

    # Join with single newline — tighter than double
    return "\n".join(compressed)


# ── COMPACT CONTEXT BUILDER ─────────────────────────────

def build_compact_context(
    location_output=None,
    legal_output=None,
    financial_output=None,
    market_output=None,
    bull_output=None,
    bear_output=None,
    dd_output=None
) -> str:
    """
    Builds one compact TOON string from multiple agent outputs.
    Used by Layer 2 (bull/bear) and Layer 3 (DD, senior) agents.

    Replaces verbose multi-summary strings with tight TOON blocks.
    Savings vs raw summaries: 50-60% input token reduction.
    """
    parts = []

    if location_output:
        parts.append(encode_summary_handoff("location", location_output))
    if legal_output:
        parts.append(encode_summary_handoff("legal", legal_output))
    if financial_output:
        parts.append(encode_summary_handoff("financial", financial_output))
    if market_output:
        parts.append(encode_summary_handoff("market", market_output))
    if bull_output:
        parts.append(encode_summary_handoff("bull", bull_output))
    if bear_output:
        parts.append(encode_summary_handoff("bear", bear_output))
    if dd_output:
        parts.append(encode_summary_handoff("dd", dd_output))

    if not parts:
        return "No prior context."

    return "\n---\n".join(parts)


# ── TOKEN ESTIMATOR + LOGGER ────────────────────────────

def estimate_tokens(text: str) -> int:
    """1 token ≈ 4 chars. Rough estimate for logging."""
    return max(1, len(text) // 4)


def log_compression(label: str, original: str, compressed: str):
    """Prints before/after token count. Call to verify savings."""
    orig = estimate_tokens(original)
    comp = estimate_tokens(compressed)
    saved = orig - comp
    pct = round((saved / orig * 100) if orig > 0 else 0, 1)
    arrow = "✅" if saved > 0 else "⚠️ no gain"
    print(f"  [TOON] {label}: {orig}→{comp} tokens | saved {saved} ({pct}%) {arrow}")