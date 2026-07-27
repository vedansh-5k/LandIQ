"""
compression_utils.py
Caveman mode and TOON compression with full stats reporting.

Usage:
    result = caveman_compress(text, mode="lite")  # or "full" / "ultra"
    result = toon_compress(text)

Both return CompressionResult with original_tokens, compressed_tokens, savings_pct, text.
"""

import re
from dataclasses import dataclass
from typing import Literal

# Rough token estimator (GPT-style: ~4 chars per token)
def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class CompressionResult:
    text: str
    original_tokens: int
    compressed_tokens: int
    savings_tokens: int
    savings_pct: float
    mode: str

    def stats_line(self) -> str:
        return (
            f"[{self.mode.upper()}] "
            f"{self.original_tokens} → {self.compressed_tokens} tokens | "
            f"saved {self.savings_tokens} tokens ({self.savings_pct:.1f}%)"
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "savings_tokens": self.savings_tokens,
            "savings_pct": round(self.savings_pct, 2),
            "stats_line": self.stats_line(),
        }


# ── CAVEMAN ────────────────────────────────────────────────────────────────────
# Three modes: lite (safe), full (aggressive), ultra (maximum loss)

_CAVEMAN_LITE = [
    (r"\b(the|a|an)\b\s*", ""),
    (r"\b(is|are|was|were)\b", "="),
    (r"\b(and)\b", "&"),
    (r"\b(with)\b", "w/"),
    (r"\b(without)\b", "w/o"),
    (r"\b(because)\b", "bc"),
    (r"\b(therefore)\b", "∴"),
    (r"\b(approximately)\b", "~"),
    (r"\b(government)\b", "govt"),
    (r"\b(information)\b", "info"),
    (r"\b(recommendation)\b", "rec"),
    (r"\b(analysis)\b", "anlys"),
    (r"\b(investment)\b", "inv"),
    (r"\b(property)\b", "prop"),
    (r"\b(location)\b", "loc"),
    (r"\b(document)\b", "doc"),
    (r"\b(registration)\b", "reg"),
    (r"\b(transaction)\b", "txn"),
    (r"\b(percentage)\b", "%"),
]

_CAVEMAN_FULL = _CAVEMAN_LITE + [
    (r"\b(you|your)\b", "u"),
    (r"\b(please)\b", "pls"),
    (r"\b(however)\b", "but"),
    (r"\b(very|extremely|highly)\b", "v."),
    (r"\b(important|critical|crucial)\b", "!"),
    (r"\b(should|must|need to)\b", "→"),
    (r"\b(market|markets)\b", "mkt"),
    (r"\b(financial|finance)\b", "fin"),
    (r"\b(development)\b", "dev"),
    (r"\b(infrastructure)\b", "infra"),
    (r"\b(residential)\b", "resid"),
    (r"\b(commercial)\b", "comm"),
    (r"\b(agricultural)\b", "agri"),
    (r"\b(authority)\b", "auth"),
    (r"\b(certificate)\b", "cert"),
    (r"\b(legal|legally)\b", "leg."),
    (r"\b(verification)\b", "verify"),
]

_CAVEMAN_ULTRA = _CAVEMAN_FULL + [
    # Remove filler phrases
    (r"it is (worth noting|important to note) that\s*", ""),
    (r"it should be noted that\s*", ""),
    (r"in order to\b", "to"),
    (r"as well as\b", "&"),
    (r"due to the fact that\b", "bc"),
    (r"at this point in time\b", "now"),
    (r"in the event that\b", "if"),
    (r"with regard to\b", "re:"),
    (r"for the purpose of\b", "for"),
    (r"it is (clear|evident|obvious) that\s*", ""),
    # Collapse multiple spaces/newlines
    (r"\n{3,}", "\n\n"),
    (r" {2,}", " "),
]

_CAVEMAN_MAPS = {
    "lite": _CAVEMAN_LITE,
    "full": _CAVEMAN_FULL,
    "ultra": _CAVEMAN_ULTRA,
}


def caveman_compress(
    text: str,
    mode: Literal["lite", "full", "ultra"] = "lite"
) -> CompressionResult:
    original_tokens = _est_tokens(text)
    rules = _CAVEMAN_MAPS.get(mode, _CAVEMAN_LITE)
    result = text
    for pattern, replacement in rules:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    # Clean up double spaces
    result = re.sub(r" {2,}", " ", result).strip()
    compressed_tokens = _est_tokens(result)
    savings = original_tokens - compressed_tokens
    pct = (savings / original_tokens * 100) if original_tokens > 0 else 0
    return CompressionResult(
        text=result,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        savings_tokens=savings,
        savings_pct=pct,
        mode=f"caveman-{mode}",
    )


# ── TOON ───────────────────────────────────────────────────────────────────────
# Tree-Of-On-Notation: convert verbose text to structured compact notation

def toon_compress(text: str) -> CompressionResult:
    """
    TOON: replace verbose prose with structured tree notation.
    - Bullet paragraphs → nested tree
    - Key: Value patterns preserved
    - Long sentences → compressed node
    """
    original_tokens = _est_tokens(text)
    lines = text.splitlines()
    output = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            output.append("")
            continue

        # Already a list item — keep, compress whitespace
        if stripped.startswith(("-", "*", "•", ">")):
            output.append(_toon_compress_line(stripped))
            continue

        # Heading
        if stripped.startswith("#"):
            output.append(stripped)
            continue

        # Key: Value pattern — keep compact
        if re.match(r"^[\w\s]{1,30}:\s+\S", stripped):
            output.append(_toon_compress_line(stripped))
            continue

        # Long sentence → compressed bullet
        words = stripped.split()
        if len(words) > 20:
            output.append("• " + _toon_compress_line(stripped))
        else:
            output.append(_toon_compress_line(stripped))

    result = "\n".join(output).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)

    compressed_tokens = _est_tokens(result)
    savings = original_tokens - compressed_tokens
    pct = (savings / original_tokens * 100) if original_tokens > 0 else 0
    return CompressionResult(
        text=result,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        savings_tokens=savings,
        savings_pct=pct,
        mode="toon",
    )


def _toon_compress_line(line: str) -> str:
    """Apply light compression to a single line for TOON."""
    # Remove filler
    line = re.sub(r"\b(the|a|an)\b\s*", "", line, flags=re.IGNORECASE)
    line = re.sub(r"\b(is|are|was|were)\b", "=", line, flags=re.IGNORECASE)
    line = re.sub(r"\b(and)\b", "&", line, flags=re.IGNORECASE)
    line = re.sub(r"\b(therefore|thus|hence)\b", "∴", line, flags=re.IGNORECASE)
    line = re.sub(r"\b(approximately|around|about)\b", "~", line, flags=re.IGNORECASE)
    line = re.sub(r" {2,}", " ", line)
    return line.strip()


# ── Combined apply (used by agent chain) ──────────────────────────────────────

def apply_compression(
    text: str,
    use_caveman: bool = False,
    caveman_mode: str = "lite",
    use_toon: bool = False,
) -> dict:
    """
    Apply any combination of compressions.
    Returns final text + list of CompressionResult stats.
    """
    stats = []
    current = text

    if use_caveman:
        r = caveman_compress(current, mode=caveman_mode)
        stats.append(r.to_dict())
        current = r.text

    if use_toon:
        r = toon_compress(current)
        stats.append(r.to_dict())
        current = r.text

    return {"text": current, "compression_stats": stats}