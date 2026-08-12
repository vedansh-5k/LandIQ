"""
headroom_bridge.py — Input Token Compression for LandIQ
========================================================
Headroom compresses INPUT tokens sent to the LLM.
Caveman compresses OUTPUT tokens from the LLM.
Together they squeeze both ends.

HOW IT WORKS:
1. Takes any text block (RAG context, agent prompt, previous outputs)
2. Removes filler words, redundant phrases, excessive whitespace
3. Shortens common phrases to abbreviations
4. Returns compressed text + stats (original vs compressed token count)

SAFE: Only compresses context/RAG text. Never touches user data or structured fields.
"""

import re
import math

# ── Filler words and phrases to remove ──────────────────────────────
FILLER_PATTERNS = [
    # Hedging / uncertainty filler
    r'\b(it is worth noting that|it should be noted that)\b',
    r'\b(it is important to note that|it is important to understand that)\b',
    r'\b(please note that|note that|notably)\b',
    r'\b(in terms of|with respect to|with regard to|in regard to)\b',
    r'\b(as mentioned earlier|as discussed above|as noted above)\b',
    r'\b(essentially|basically|fundamentally|generally speaking)\b',
    r'\b(it can be said that|it may be noted that)\b',
    r'\b(in order to)\b',  # → "to"
    r'\b(due to the fact that)\b',  # → "because"
    r'\b(at this point in time|at the present time)\b',  # → "now"
    r'\b(in the event that)\b',  # → "if"
    r'\b(for the purpose of)\b',  # → "for"
    r'\b(on a daily basis)\b',  # → "daily"
    r'\b(a large number of)\b',  # → "many"
    r'\b(the vast majority of)\b',  # → "most"
    r'\b(in close proximity to)\b',  # → "near"
    r'\b(has the ability to)\b',  # → "can"
    r'\b(is able to)\b',  # → "can"
    r'\b(make sure that|ensure that)\b',
    r'\b(take into consideration|take into account)\b',
    r'\b(on the other hand|having said that|that being said)\b',
    r'\b(as a matter of fact|in actual fact)\b',
    r'\b(each and every)\b',  # → "every"
    r'\b(first and foremost)\b',  # → "first"
]

# ── Smart replacements (long phrase → short equivalent) ─────────────
REPLACEMENTS = [
    (r'\bdue to the fact that\b', 'because'),
    (r'\bin order to\b', 'to'),
    (r'\bat this point in time\b', 'now'),
    (r'\bat the present time\b', 'now'),
    (r'\bin the event that\b', 'if'),
    (r'\bfor the purpose of\b', 'for'),
    (r'\bon a daily basis\b', 'daily'),
    (r'\ba large number of\b', 'many'),
    (r'\bthe vast majority of\b', 'most'),
    (r'\bin close proximity to\b', 'near'),
    (r'\bhas the ability to\b', 'can'),
    (r'\bis able to\b', 'can'),
    (r'\beach and every\b', 'every'),
    (r'\bfirst and foremost\b', 'first'),
    (r'\bin the near future\b', 'soon'),
    (r'\bat the end of the day\b', 'ultimately'),
    (r'\bthe fact that\b', 'that'),
    (r'\bwhether or not\b', 'whether'),
    (r'\buntil such time as\b', 'until'),
    (r'\bprior to\b', 'before'),
    (r'\bsubsequent to\b', 'after'),
    (r'\bin the vicinity of\b', 'near'),
    (r'\ba total of\b', ''),
    (r'\bit is recommended that\b', 'recommend'),
    (r'\bit is suggested that\b', 'suggest'),
    (r'\bit is anticipated that\b', 'expect'),
    (r'\bin light of\b', 'given'),
    (r'\bwith the exception of\b', 'except'),
    (r'\bfor the most part\b', 'mostly'),
    (r'\bin most cases\b', 'usually'),
    (r'\bin some cases\b', 'sometimes'),
    (r'\bas a result of\b', 'from'),
    (r'\bon the basis of\b', 'based on'),
    (r'\bin accordance with\b', 'per'),
    (r'\bpertaining to\b', 'about'),
    (r'\bwith reference to\b', 'about'),
    (r'\bin conjunction with\b', 'with'),
    (r'\bby means of\b', 'via'),
    (r'\bin the amount of\b', 'of'),
]

# ── Redundant article patterns (safe removal) ──────────────────────
ARTICLE_PATTERNS = [
    r'\b(the|a|an)\s+(?=\w+\s+(is|are|was|were|has|have|will|can|should|may|might))',
]


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(1, math.ceil(len(text) / 4))


def compress_input(text: str, level: str = "full") -> dict:
    """
    Compress input text to reduce token count.
    
    Args:
        text: Raw text (RAG context, agent output, prompt text)
        level: "lite" | "full" | "ultra"
            lite  — only remove obvious filler phrases
            full  — filler + smart replacements + whitespace cleanup
            ultra — full + article removal + aggressive shortening
    
    Returns:
        dict with keys:
            compressed: the compressed text
            original_tokens: estimated token count before
            compressed_tokens: estimated token count after
            savings_pct: percentage saved
            level: compression level used
    """
    if not text or not text.strip():
        return {
            "compressed": text or "",
            "original_tokens": 0,
            "compressed_tokens": 0,
            "savings_pct": 0,
            "level": level
        }
    
    original = text
    original_tokens = _estimate_tokens(original)
    
    # ── Level: LITE — just remove filler phrases ────────────────────
    if level in ("lite", "full", "ultra"):
        for pattern in FILLER_PATTERNS:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # ── Level: FULL — smart replacements ────────────────────────────
    if level in ("full", "ultra"):
        for pattern, replacement in REPLACEMENTS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    # ── Level: ULTRA — remove articles + aggressive cleanup ────────
    if level == "ultra":
        for pattern in ARTICLE_PATTERNS:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        # Remove standalone articles before nouns
        text = re.sub(r'\b(the|a|an)\s+', '', text, flags=re.IGNORECASE)
    
    # ── Common cleanup (all levels) ─────────────────────────────────
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)   # triple+ newlines → double
    text = re.sub(r'  +', ' ', text)                   # multiple spaces → single
    text = re.sub(r' +([.,;:!?])', r'\1', text)        # space before punctuation
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)  # leading whitespace per line
    text = text.strip()
    
    compressed_tokens = _estimate_tokens(text)
    savings = original_tokens - compressed_tokens
    savings_pct = round((savings / original_tokens * 100), 1) if original_tokens > 0 else 0
    
    return {
        "compressed": text,
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "savings_pct": savings_pct,
        "level": level
    }


def compress_rag_context(rag_text: str, level: str = "full") -> dict:
    """
    Specifically compress RAG context — the biggest input token consumer.
    RAG chunks often have repetitive boilerplate from source documents.
    """
    if not rag_text:
        return compress_input("", level)
    
    # Additional RAG-specific cleanup
    # Remove repeated source attribution lines
    text = re.sub(r'(Source:|Reference:|Document:).*?\n', '', rag_text)
    # Remove "According to the document..." type prefixes
    text = re.sub(r'\b(according to|as per|as stated in)\b\s*(the|this)?\s*(document|report|source|data)s?\s*,?\s*', '', text, flags=re.IGNORECASE)
    
    return compress_input(text, level)


def compress_agent_context(agent_outputs: dict, level: str = "full") -> dict:
    """
    Compress previous agent outputs before passing to next layer.
    Returns compressed version + total stats.
    """
    if not agent_outputs:
        return {"compressed": {}, "total_original": 0, "total_compressed": 0, "savings_pct": 0}
    
    compressed = {}
    total_orig = 0
    total_comp = 0
    
    for key, value in agent_outputs.items():
        if isinstance(value, str):
            result = compress_input(value, level)
            compressed[key] = result["compressed"]
            total_orig += result["original_tokens"]
            total_comp += result["compressed_tokens"]
        elif isinstance(value, dict):
            # Compress each string value in the dict
            compressed[key] = {}
            for k, v in value.items():
                if isinstance(v, str) and len(v) > 50:  # only compress substantial text
                    result = compress_input(v, level)
                    compressed[key][k] = result["compressed"]
                    total_orig += result["original_tokens"]
                    total_comp += result["compressed_tokens"]
                else:
                    compressed[key][k] = v
        else:
            compressed[key] = value
    
    savings = total_orig - total_comp
    savings_pct = round((savings / total_orig * 100), 1) if total_orig > 0 else 0
    
    return {
        "compressed": compressed,
        "total_original": total_orig,
        "total_compressed": total_comp,
        "savings_pct": savings_pct
    }


# ── Quick test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    sample = """
    It is worth noting that the property in Sector 62, Gurugram has a relatively 
    low flood risk. In terms of environmental clearances, it should be noted that 
    the area has moderate pollution levels. Due to the fact that the nearby Dwarka 
    Expressway is under construction, it is anticipated that property values will 
    increase in the near future. A large number of homebuyers are showing interest 
    in this area. The vast majority of transactions in this micro-market have been 
    for residential purposes. In order to make an informed decision, it is recommended 
    that the investor take into consideration the environmental risk score of 82.
    """
    
    print("=" * 50)
    print("HEADROOM — Input Token Compression Test")
    print("=" * 50)
    
    for lvl in ("lite", "full", "ultra"):
        r = compress_input(sample, lvl)
        print(f"\n[{lvl.upper()}] {r['original_tokens']} → {r['compressed_tokens']} tokens ({r['savings_pct']}% saved)")
        print(f"Text: {r['compressed'][:150]}...")