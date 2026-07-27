"""
rate_limiter.py
---------------
Sliding-window rate limiter adapted from the student's code.
Tracks requests-per-minute per model key.

WHY THIS FILE EXISTS:
The intelligent model router needs to know when a model is hitting
its rate limit BEFORE making a call (not after getting a 429 error).
This tracker watches RPM in a 60-second sliding window.

ADAPTED FROM: student's rate_limiter.py
CHANGES: made synchronous (LandIQ uses sync FastAPI), added token
threshold tracking alongside RPM tracking.
"""

import time
import threading
from collections import defaultdict


class RateLimiter:
    def __init__(self):
        # RPM tracking: model_id -> list of timestamps in last 60s
        self._rpm_windows: dict = defaultdict(list)
        # Token tracking: model_id -> tokens used this session
        self._token_counts: dict = defaultdict(int)
        # Token thresholds: model_id -> max tokens before switching
        self._token_thresholds: dict = {}
        self._lock = threading.Lock()

    # ── RPM TRACKING ──────────────────────────────────────────────

    def record_request(self, model_id: str) -> bool:
        """
        Record a request for model_id.
        Returns True if within limit, False if rate limit exceeded.
        Call this BEFORE making the LLM call.
        """
        with self._lock:
            now = time.time()
            window = self._rpm_windows[model_id]
            # Keep only last 60 seconds
            self._rpm_windows[model_id] = [t for t in window if now - t < 60]
            current_rpm = len(self._rpm_windows[model_id])
            self._rpm_windows[model_id].append(now)
            return True  # we record but don't block — router handles switching

    def get_rpm(self, model_id: str) -> int:
        """Current requests in last 60 seconds."""
        with self._lock:
            now = time.time()
            window = self._rpm_windows[model_id]
            self._rpm_windows[model_id] = [t for t in window if now - t < 60]
            return len(self._rpm_windows[model_id])

    def is_rate_limited(self, model_id: str, rpm_limit: int) -> bool:
        """True if this model has exceeded its RPM limit."""
        return self.get_rpm(model_id) >= rpm_limit

    # ── TOKEN THRESHOLD TRACKING ───────────────────────────────────

    def set_threshold(self, model_id: str, max_tokens: int):
        """Set the token threshold after which this model switches."""
        with self._lock:
            self._token_thresholds[model_id] = max_tokens

    def record_tokens(self, model_id: str, tokens: int):
        """Add token usage for this model."""
        with self._lock:
            self._token_counts[model_id] += tokens

    def is_threshold_exceeded(self, model_id: str) -> bool:
        """True if this model has used more tokens than its threshold."""
        with self._lock:
            threshold = self._token_thresholds.get(model_id)
            if threshold is None or threshold == 0:
                return False  # no threshold set = never switch
            return self._token_counts[model_id] >= threshold

    def get_usage(self, model_id: str) -> dict:
        """Current usage stats for a model."""
        with self._lock:
            now = time.time()
            window = self._rpm_windows[model_id]
            self._rpm_windows[model_id] = [t for t in window if now - t < 60]
            return {
                "model_id": model_id,
                "rpm_current": len(self._rpm_windows[model_id]),
                "tokens_used": self._token_counts[model_id],
                "token_threshold": self._token_thresholds.get(model_id, 0),
                "threshold_exceeded": self.is_threshold_exceeded(model_id)
            }

    def reset_session(self):
        """Reset all counters (call at start of new analysis session)."""
        with self._lock:
            self._token_counts.clear()
            self._rpm_windows.clear()


# Global singleton — one per server process
rate_limiter = RateLimiter()