"""
caveman_mode.py
---------------
Caveman token compression for LandIQ.

Strategy: instead of injecting verbose rules (which add
input tokens), we simply tell agents to write SHORT summaries.
This reduces output tokens on the summary field cleanly.

In structured output agents, only free-text fields compress.
Required fields (scores, percentages, risk levels) always
output in full regardless — model must fill them.
"""

_caveman_active = False
_caveman_level = "full"


def set_caveman(active: bool, level: str = "full"):
    global _caveman_active, _caveman_level
    _caveman_active = active
    _caveman_level = level if level in ["lite", "full", "ultra"] else "full"
    print(f"  [CAVEMAN] {'ON' if active else 'OFF'} — {_caveman_level.upper()}")


def is_active() -> bool:
    return _caveman_active


def get_level() -> str:
    return _caveman_level


def inject_caveman(system_prompt: str) -> str:
    """
    Adds a single short line to system prompt.
    Minimal input token cost (~15 tokens).
    Reduces summary field output by ~40-60%.
    """
    if not _caveman_active:
        return system_prompt

    rules = {
        "lite": "\nIMPORTANT: Keep summary field under 30 words. Facts only. No filler.",
        "full": "\nIMPORTANT: Summary field must be under 20 words. Fragments OK. No articles or filler words.",
        "ultra": "\nIMPORTANT: Summary field max 10 words. Fragments only. No filler."
    }
    return system_prompt + rules.get(_caveman_level, rules["full"])