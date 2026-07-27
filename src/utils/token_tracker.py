"""
token_tracker.py
Tracks per-agent token usage across a session.
"""

from dataclasses import dataclass, field
from typing import Dict
import time


@dataclass
class AgentTokenRecord:
    agent_name: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self):
        return self.input_tokens + self.output_tokens


class TokenTracker:
    def __init__(self):
        self._records: Dict[str, AgentTokenRecord] = {}
        self._session_start = None

    def reset(self):
        self._records = {}
        self._session_start = time.time()

    def _store(self, agent_name: str, input_tokens: int, output_tokens: int):
        """Store token usage for an agent."""
        if agent_name not in self._records:
            self._records[agent_name] = AgentTokenRecord(agent_name)
        self._records[agent_name].input_tokens += input_tokens
        self._records[agent_name].output_tokens += output_tokens

    def get_summary(self) -> dict:
        total_in  = sum(r.input_tokens  for r in self._records.values())
        total_out = sum(r.output_tokens for r in self._records.values())
        total     = total_in + total_out
        cost      = (total / 1_000_000) * 0.27
        duration  = round(time.time() - self._session_start, 2) if self._session_start else 0

        return {
            "duration_seconds": duration,
            "total_llm_calls": len(self._records),
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total,
            "estimated_cost_usd": round(cost, 4),
            "per_agent": {
                name: {"in": r.input_tokens, "out": r.output_tokens, "total": r.total}
                for name, r in self._records.items()
            }
        }

    def get_token_report(self) -> dict:
        """
        Returns token report in the exact format the frontend expects.
        Called by orchestrator_agent.py at end of run.
        """
        total_in  = sum(r.input_tokens  for r in self._records.values())
        total_out = sum(r.output_tokens for r in self._records.values())
        total     = total_in + total_out
        cost      = (total / 1_000_000) * 0.27
        duration  = round(time.time() - self._session_start, 2) if self._session_start else 0

        # per_agent_log — array format the frontend renders in the token table
        per_agent_log = [
            {
                "agent":         name,
                "input_tokens":  r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens":  r.total,
            }
            for name, r in self._records.items()
        ]

        return {
            # ── top-level stats (all field names the frontend checks) ──
            "duration_seconds":    duration,
            "session_duration_seconds": duration,
            "total_llm_calls":     len(self._records),
            "input_tokens":        total_in,
            "output_tokens":       total_out,
            "total_tokens":        total,
            "estimated_cost_usd":  round(cost, 6),
            # ── per-agent array ──
            "per_agent_log":       per_agent_log,
        }

    def print_report(self):
        s = self.get_summary()
        print("\n" + "=" * 60)
        print("  TOKEN CONSUMPTION REPORT — LandIQ")
        print("=" * 60)
        print(f"  Session Duration   : {s['duration_seconds']}s")
        print(f"  Total LLM Calls    : {s['total_llm_calls']}")
        print(f"  Input Tokens       : {s['input_tokens']}")
        print(f"  Output Tokens      : {s['output_tokens']}")
        print(f"  Total Tokens       : {s['total_tokens']}")
        print(f"  Estimated Cost     : ${s['estimated_cost_usd']} USD")
        print("-" * 60)
        print(f"  {'Agent':<35} {'IN':>6} {'OUT':>5} {'TOTAL':>7}")
        print(f"  {'-'*35} {'-'*6} {'-'*5} {'-'*7}")
        for name, data in s['per_agent'].items():
            flag = " *" if data['total'] == 0 else ""
            print(f"  {name:<35} {data['in']:>6} {data['out']:>5} {data['total']:>7}{flag}")
        if any(d['total'] == 0 for d in s['per_agent'].values()):
            print("\n  * = agent failed or token capture unavailable")
        print("=" * 60 + "\n")


# Global singleton
tracker = TokenTracker()


def get_token_report() -> dict:
    """Module-level function — called by orchestrator_agent.py"""
    return tracker.get_token_report()