"""
headroom_bridge.py
------------------
Integrates Headroom (context compression) into LandIQ.

What Headroom does:
  Compresses INPUT tokens (prompts, RAG chunks, tool outputs, JSON)
  before they reach the LLM. Same answer, 60-95% fewer input tokens.

How it works here:
  - Hooks into LiteLLM via HeadroomCallback (one-line integration)
  - Every LLM call through LiteLLM Router gets compressed automatically
  - Toggleable: enable()/disable() per-request via headroom_mode flag
  - Safe fallback: if headroom-ai is not installed, everything still works

Install:
  pip install headroom-ai --break-system-packages

Usage in api.py:
  from src.utils.headroom_bridge import headroom_ctx
  # Inside /analyse:
  with headroom_ctx(req.headroom_mode):
      result = run_dynamic_advisor(user_inputs)
  # Stats auto-collected
"""

import logging
import re
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ── State ───────────────────────────────────────────────────────────
_available = False
_enabled = False
_callback_instance = None
_stats = {
    "enabled": False,
    "available": False,
    "tokens_before": 0,
    "tokens_after": 0,
    "tokens_saved": 0,
    "compression_ratio": 0.0,
    "calls_compressed": 0,
}

try:
    from headroom.integrations.litellm_callback import HeadroomCallback
    _available = True
    logger.info("[HEADROOM] headroom-ai is installed and available")
except ImportError:
    logger.info("[HEADROOM] headroom-ai not installed — headroom_mode will be skipped")


def is_available():
    """Check if headroom-ai package is installed."""
    return _available


def is_enabled():
    """Check if headroom compression is currently active."""
    return _enabled


def enable():
    """Enable Headroom compression for all LiteLLM calls."""
    global _enabled, _callback_instance
    if not _available:
        logger.warning("[HEADROOM] Cannot enable — headroom-ai not installed. "
                       "Run: pip install headroom-ai --break-system-packages")
        return False

    try:
        import litellm
        from headroom.integrations.litellm_callback import HeadroomCallback

        # Don't add duplicate callbacks
        if _callback_instance is not None:
            return True

        _callback_instance = HeadroomCallback()

        if not hasattr(litellm, 'callbacks') or litellm.callbacks is None:
            litellm.callbacks = []
        litellm.callbacks.append(_callback_instance)

        _enabled = True
        logger.info("[HEADROOM] Enabled — all LiteLLM calls will be compressed")
        return True

    except Exception as e:
        logger.error(f"[HEADROOM] Failed to enable: {e}")
        return False


def disable():
    """Disable Headroom compression."""
    global _enabled, _callback_instance
    if not _enabled:
        return

    try:
        import litellm
        if hasattr(litellm, 'callbacks') and litellm.callbacks and _callback_instance:
            litellm.callbacks = [
                cb for cb in litellm.callbacks
                if cb is not _callback_instance
            ]
        _callback_instance = None
        _enabled = False
        logger.info("[HEADROOM] Disabled")
    except Exception as e:
        logger.error(f"[HEADROOM] Failed to disable: {e}")


def reset_stats():
    """Reset per-request stats."""
    global _stats
    _stats = {
        "enabled": _enabled,
        "available": _available,
        "tokens_before": 0,
        "tokens_after": 0,
        "tokens_saved": 0,
        "compression_ratio": 0.0,
        "calls_compressed": 0,
    }


def get_stats():
    """Get current compression stats."""
    return dict(_stats)


def compress_text(text, model="groq/llama-3.3-70b-versatile"):
    """
    Manually compress a single text string.
    Useful for compressing RAG context or agent prompts directly.
    Returns dict with before/after/saved token counts.
    """
    if not _available:
        return {
            "original": text,
            "compressed": text,
            "tokens_before": 0,
            "tokens_after": 0,
            "tokens_saved": 0,
            "ratio": 0.0,
            "headroom_available": False,
        }

    try:
        from headroom import compress
        messages = [{"role": "user", "content": text}]
        result = compress(messages, model=model)

        compressed_text = text
        if result.messages and len(result.messages) > 0:
            compressed_text = result.messages[0].get("content", text)

        return {
            "original": text,
            "compressed": compressed_text,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "tokens_saved": result.tokens_saved,
            "ratio": result.compression_ratio,
            "headroom_available": True,
        }
    except Exception as e:
        logger.error(f"[HEADROOM] compress_text failed: {e}")
        return {
            "original": text,
            "compressed": text,
            "tokens_before": 0,
            "tokens_after": 0,
            "tokens_saved": 0,
            "ratio": 0.0,
            "headroom_available": True,
            "error": str(e)[:200],
        }


@contextmanager
def headroom_ctx(should_enable=False):
    """
    Context manager for per-request headroom toggling.

    Usage:
        with headroom_ctx(req.headroom_mode):
            result = run_dynamic_advisor(user_inputs)
        stats = get_stats()

    If should_enable=False or headroom not installed, does nothing.
    Always disables after the block, so next request starts clean.
    """
    reset_stats()

    if should_enable and _available:
        enabled = enable()
        _stats["enabled"] = enabled
        _stats["available"] = True
    else:
        _stats["enabled"] = False
        _stats["available"] = _available

    try:
        yield
    finally:
        if should_enable and _enabled:
            disable()


# ── Manual regex-based compression (independent of the headroom-ai pkg) ──
# Compresses actual prompt TEXT before it reaches the LLM. Unlike compress_text()
# above (which needs the headroom-ai package's litellm callback wired into a
# litellm completion() call), this works on any plain string and never depends
# on litellm/headroom-ai being installed or intercepting the call path used by
# ChatGroq/ChatGoogleGenerativeAI .invoke().

_FILLER_PHRASES = [
    r"it is worth noting that\s*",
    r"it should be noted that\s*",
    r"as a matter of fact,?\s*",
    r"at the end of the day,?\s*",
    r"in the context of\s*",
    r"with respect to\s*",
    r"it is important to note that\s*",
    r"it is important to note\s*",
]

_SHORTEN_PHRASES = [
    (r"in order to\b", "to"),
    (r"due to the fact that\b", "because"),
    (r"at this point in time\b", "now"),
    (r"in the event that\b", "if"),
    (r"for the purpose of\b", "for"),
    (r"in the near future\b", "soon"),
    (r"a large number of\b", "many"),
    (r"on a daily basis\b", "daily"),
]

_ENC2 = None
_ENC2_TRIED = False


def _hr_encoder():
    global _ENC2, _ENC2_TRIED
    if _ENC2_TRIED:
        return _ENC2
    _ENC2_TRIED = True
    try:
        import tiktoken
        _ENC2 = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENC2 = None
    return _ENC2


def _hr_count_tokens(text):
    """Real token count via tiktoken when available, else ~0.75 words/token."""
    if not text:
        return 0
    enc = _hr_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    words = len(text.split())
    return max(1, round(words / 0.75))


def _dedupe_blocks(text):
    """Drop exact-duplicate paragraph/chunk blocks (e.g. repeated RAG context)."""
    blocks = re.split(r"\n\s*\n", text)
    seen = set()
    kept = []
    for b in blocks:
        key = b.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        kept.append(b)
    return "\n\n".join(kept)


def headroom_compress(text: str) -> dict:
    """
    Manual input-token compression for a prompt string (system + human + RAG
    text, however the caller has combined it). Safe: on any failure, returns
    the original text unchanged with zero measured savings.

    Returns: {compressed_text, original_tokens, compressed_tokens, savings_pct}
    """
    if not text:
        return {"compressed_text": text or "", "original_tokens": 0,
                "compressed_tokens": 0, "savings_pct": 0.0}

    original_tokens = _hr_count_tokens(text)

    try:
        result = text

        # Strip HTML tags if present
        result = re.sub(r"<[^>]+>", " ", result)

        # Shorten common phrases
        for pattern, repl in _SHORTEN_PHRASES:
            result = re.sub(pattern, repl, result, flags=re.IGNORECASE)

        # Remove filler phrases entirely
        for pattern in _FILLER_PHRASES:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE)

        # Deduplicate repeated paragraph/context blocks
        result = _dedupe_blocks(result)

        # Collapse redundant whitespace / repeated blank lines
        result = re.sub(r"[ \t]{2,}", " ", result)
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = "\n".join(line.rstrip() for line in result.split("\n"))
        result = result.strip()

        compressed_tokens = _hr_count_tokens(result)
        saved = original_tokens - compressed_tokens
        pct = (saved / original_tokens * 100) if original_tokens > 0 else 0.0

        return {
            "compressed_text": result,
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "savings_pct": round(pct, 2),
        }
    except Exception as e:
        logger.warning(f"[HEADROOM] headroom_compress failed, returning original: {e}")
        return {"compressed_text": text, "original_tokens": original_tokens,
                "compressed_tokens": original_tokens, "savings_pct": 0.0}


# ── Session-level accumulator for manual compression (thread-safe) ───────
# Mirrors the pattern used by src.utils.tracked_chain for token accounting,
# so stats survive the orchestrator's ThreadPoolExecutor-based agent layers.
_manual_lock = threading.Lock()
_manual_session = {"original_tokens": 0, "compressed_tokens": 0, "calls": 0}


def reset_manual_session():
    global _manual_session
    with _manual_lock:
        _manual_session = {"original_tokens": 0, "compressed_tokens": 0, "calls": 0}


def record_manual_compression(original_tokens, compressed_tokens):
    with _manual_lock:
        _manual_session["original_tokens"] += int(original_tokens or 0)
        _manual_session["compressed_tokens"] += int(compressed_tokens or 0)
        _manual_session["calls"] += 1


def get_manual_session_stats():
    """Real, measured headroom savings for the current /analyse session, or
    None if headroom_mode was never on (no calls compressed)."""
    with _manual_lock:
        orig = _manual_session["original_tokens"]
        comp = _manual_session["compressed_tokens"]
        calls = _manual_session["calls"]
    if calls == 0:
        return None
    saved = orig - comp
    pct = (saved / orig * 100) if orig > 0 else 0.0
    return {
        "original_tokens": orig,
        "compressed_tokens": comp,
        "savings_tokens": saved,
        "savings_pct": round(pct, 2),
        "calls_compressed": calls,
    }


# ── Direct compress() wrapper for one-off testing ──────────────────
def test_compression(text="The residential property located in Whitefield, "
                          "Bangalore, Karnataka has been analysed by the "
                          "Location Intelligence Agent. The current price "
                          "range is estimated at Rs 3500-4500 per sq yard "
                          "based on comparable areas like Kundanahalli and "
                          "Hoodi. The upcoming Namma Metro Phase 2 extension "
                          "is expected to increase demand by 15-20%."):
    """Quick test to verify headroom is working. Run from terminal:
       python -c "from src.utils.headroom_bridge import test_compression; test_compression()"
    """
    result = compress_text(text)
    print(f"\n{'='*50}")
    print(f"  HEADROOM TEST")
    print(f"{'='*50}")
    print(f"  Available : {result['headroom_available']}")
    print(f"  Before    : {result['tokens_before']} tokens")
    print(f"  After     : {result['tokens_after']} tokens")
    print(f"  Saved     : {result['tokens_saved']} tokens")
    print(f"  Ratio     : {result['ratio']:.1%}")
    if result.get('error'):
        print(f"  Error     : {result['error']}")
    print(f"{'='*50}\n")
    return result
