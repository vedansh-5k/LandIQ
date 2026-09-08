"""
facts_store.py
---------------
Structured, sourced "verified facts" layer for LandIQ — sits ABOVE the PDF-chunk
text RAG in trust order. Text RAG retrieves prose from general market reports;
this retrieves exact, dated, sourced numbers for one specific locality when
someone has actually gone and recorded them.

Not hardcoded: every locality is a JSON file under data/land_facts/<state>/<city>/
<area>.json. Adding a new locality means adding a file — zero code changes,
same pattern src/utils/agent_loader.py already uses for agents_registry/.

A file that isn't there simply isn't there — get_structured_facts() returns
None cleanly (mirrors pixelrag_bridge.search()'s fail-quiet style) and the
caller falls back to text RAG / general knowledge, clearly labelled as such.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_FACTS_ROOT = None


def _get_facts_root():
    global _FACTS_ROOT
    if _FACTS_ROOT and Path(_FACTS_ROOT).is_dir():
        return Path(_FACTS_ROOT)

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "data" / "land_facts",
        Path.cwd() / "data" / "land_facts",
    ]
    for c in candidates:
        if c.is_dir():
            _FACTS_ROOT = str(c)
            return c

    # Nothing recorded yet — don't crash, just report "no facts folder".
    return None


def _normalize(s):
    """'Sector 44' / 'sec-44' / 'Sector-44 ' all collapse to 'sector44'."""
    if not s:
        return ""
    s = str(s).lower().strip()
    s = s.replace("sec.", "sector").replace("sec ", "sector ").replace("sec-", "sector-")
    return re.sub(r"[^a-z0-9]", "", s)


def _load_all_facts():
    root = _get_facts_root()
    if root is None:
        return []
    entries = []
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_file"] = str(path)
            entries.append(data)
        except Exception as e:
            logger.warning("[facts_store] failed to parse %s: %s", path, e)
    return entries


def get_structured_facts(area, city, state):
    """
    Returns {"match": <exact locality dict or None>, "nearby": [<up to 3 same-city
    localities>]}, or None entirely if the facts store has nothing indexed at all
    (distinct from "indexed but no match", which returns match=None, nearby=[]).
    """
    entries = _load_all_facts()
    if not entries:
        return None

    n_area, n_city = _normalize(area), _normalize(city)

    match = None
    same_city = []
    for e in entries:
        e_city = _normalize(e.get("city", ""))
        if n_city and e_city != n_city:
            continue
        e_area = _normalize(e.get("area", ""))
        if n_area and e_area == n_area:
            match = e
        else:
            same_city.append(e)

    nearby = [e for e in same_city if e is not match][:3]
    return {"match": match, "nearby": nearby}


def format_structured_facts_block(facts):
    """Renders the facts dict (from get_structured_facts) into the prompt block
    text. Returns None if there's genuinely nothing to show, so the caller can
    fall back cleanly instead of printing an empty section."""
    if not facts or (not facts.get("match") and not facts.get("nearby")):
        return None

    lines = []

    m = facts.get("match")
    if m:
        lines.append(_format_entry(m, label="VERIFIED for %s, %s" % (m.get("area", ""), m.get("city", ""))))

    for e in facts.get("nearby") or []:
        lines.append(_format_entry(e, label="NEARBY COMPARABLE — %s, %s (not the exact locality, use as context only)"
                                     % (e.get("area", ""), e.get("city", ""))))

    return "\n\n".join(lines) if lines else None


def _format_entry(e, label):
    price_range = e.get("price_per_sqyd_range") or {}
    pmin, pmax = price_range.get("min"), price_range.get("max")
    price_str = ("Rs.%s - Rs.%s per sq yd" % (format(pmin, ",") if pmin else "?",
                                               format(pmax, ",") if pmax else "?")
                 if (pmin or pmax) else "not recorded")
    sqft = e.get("price_per_sqft")
    trend = e.get("yoy_trend_pct")
    projects = e.get("notable_projects") or []
    infra = e.get("infra_notes") or ""
    comparables = e.get("comparable_localities") or []

    ptype = e.get("property_type") or "not specified"

    return (
        "[%s]\n"
        "  Property type: %s (do not treat as raw land/plot rate unless it says so)\n"
        "  Price/sq yd : %s\n"
        "  Price/sq ft : %s\n"
        "  YoY trend   : %s\n"
        "  Notable     : %s\n"
        "  Infra notes : %s\n"
        "  Comparable localities: %s\n"
        "  Source: %s (%s), recorded %s | Confidence: %s"
    ) % (
        label, ptype, price_str,
        ("Rs.%s" % format(sqft, ",")) if sqft else "not recorded",
        ("%s%%" % trend) if trend is not None else "not recorded",
        ", ".join(projects) if projects else "none recorded",
        infra or "none recorded",
        ", ".join(comparables) if comparables else "none recorded",
        e.get("source_name", "unknown"), e.get("source_url", "no url"),
        e.get("date_collected", "unknown date"), e.get("confidence", "unrated"),
    )
