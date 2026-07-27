"""
tracked_chain.py - LandIQ session token accumulator
"""
import threading
import time

print("[tracked_chain] loaded")

_lock = threading.Lock()

PRICING = {
    "groq":     (0.59, 0.79),
    "gemini":   (0.10, 0.40),
    "router":   (0.59, 0.79),
    "external": (0.59, 0.79),
}
_DEFAULT_RATE = (0.59, 0.79)

_session = {"calls": [], "input": 0, "output": 0, "start": time.time()}


def reset_token_report():
    with _lock:
        _session["calls"] = []
        _session["input"] = 0
        _session["output"] = 0
        _session["start"] = time.time()
    print("  [TOKENS] session counter reset")


def record_agent_tokens(agent, input_tokens, output_tokens,
                        provider="groq", exact=False):
    it = int(input_tokens or 0)
    ot = int(output_tokens or 0)
    rin, rout = PRICING.get(str(provider).lower(), _DEFAULT_RATE)
    cost = (it / 1000000.0) * rin + (ot / 1000000.0) * rout
    with _lock:
        _session["input"] += it
        _session["output"] += ot
        _session["calls"].append({
            "agent": agent, "provider": provider,
            "input_tokens": it, "output_tokens": ot,
            "total_tokens": it + ot, "cost_usd": round(cost, 8),
            "exact": bool(exact),
        })


def get_token_report():
    with _lock:
        calls = list(_session["calls"])
        it = _session["input"]
        ot = _session["output"]
        start = _session["start"]

    tt = it + ot
    cost = round(sum(c["cost_usd"] for c in calls), 6)

    by_provider = {}
    for c in calls:
        b = by_provider.setdefault(c["provider"], {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "cost_usd": 0.0})
        b["calls"] += 1
        b["input_tokens"] += c["input_tokens"]
        b["output_tokens"] += c["output_tokens"]
        b["total_tokens"] += c["total_tokens"]
        b["cost_usd"] = round(b["cost_usd"] + c["cost_usd"], 8)

    n_exact = sum(1 for c in calls if c["exact"])
    if not calls:
        method = "none"
    elif n_exact == len(calls):
        method = "provider_reported"
    elif n_exact == 0:
        method = "locally_counted"
    else:
        method = "mixed"

    in_cost = round(sum((c["input_tokens"] / 1000000.0)
                        * PRICING.get(str(c["provider"]).lower(), _DEFAULT_RATE)[0]
                        for c in calls), 6)

    return {
        "total_llm_calls": len(calls),
        "input_tokens": it,
        "output_tokens": ot,
        "total_tokens": tt,
        "estimated_cost_usd": cost,
        "cost_breakdown": {"input_cost_usd": in_cost,
                           "output_cost_usd": max(round(cost - in_cost, 6), 0.0)},
        "session_duration_seconds": round(time.time() - start, 2),
        "counting_method": method,
        "exact_calls": n_exact,
        "by_provider": by_provider,
        "per_agent_log": calls,
    }


def print_token_report():
    r = get_token_report()
    print("\n" + "=" * 68)
    print("              TOKEN CONSUMPTION REPORT - LandIQ")
    print("=" * 68)
    if not r["total_llm_calls"]:
        print("  NO CALLS RECORDED.")
        print("  Look above for lines starting '[TOKENS]' - they carry the reason.")
        print("=" * 68 + "\n")
        return
    print("  Duration        : %ss" % r["session_duration_seconds"])
    print("  LLM Calls       : %d" % r["total_llm_calls"])
    print("  Input Tokens    : {:,}".format(r["input_tokens"]))
    print("  Output Tokens   : {:,}".format(r["output_tokens"]))
    print("  Total Tokens    : {:,}".format(r["total_tokens"]))
    print("  Estimated Cost  : $%s USD" % r["estimated_cost_usd"])
    print("  Counting Method : %s (%d/%d provider-reported)"
          % (r["counting_method"], r["exact_calls"], r["total_llm_calls"]))
    print("-" * 68)
    print("  %-28s %-9s %8s %8s %9s" % ("Agent", "Provider", "IN", "OUT", "TOTAL"))
    print("  %-28s %-9s %8s %8s %9s" % ("-"*28, "-"*9, "-"*8, "-"*8, "-"*9))
    for c in r["per_agent_log"]:
        print("  %-28s %-9s %8s %8s %9s"
              % (str(c["agent"])[:28], str(c["provider"])[:9],
                 "{:,}".format(c["input_tokens"]),
                 "{:,}".format(c["output_tokens"]),
                 "{:,}".format(c["total_tokens"])))
    if r["by_provider"]:
        print("-" * 68)
        for p, b in r["by_provider"].items():
            print("  %-9s calls=%-3d tokens=%-10s cost=$%s"
                  % (p, b["calls"], "{:,}".format(b["total_tokens"]),
                     round(b["cost_usd"], 6)))
    print("=" * 68 + "\n")