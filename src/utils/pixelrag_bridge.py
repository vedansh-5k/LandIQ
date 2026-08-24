"""
pixelrag_bridge.py
-------------------
Connects LandIQ to PixelRAG (visual RAG — screenshot-based document search).
Dual-path, same shape as langflow_bridge.py: try PixelRAG's serve API first,
return None/[] on any failure so the caller falls back to plain text RAG.

Runtime config (base_url) is stored in PIXELRAG_STATE_FILE and can be changed
live via /pixelrag/set-url — nothing here is hardcoded. Falls back to the
PIXELRAG_BASE_URL env var, then a default localhost port, when no runtime
override has been set yet.

PixelRAG's serve API (see pixelrag_serve/api.py):
  GET  /health                     -> {"status": "ok"} when the index is loaded
  POST /search  {"queries":[{"text": "..."}], "n_docs": N, "include_images": true}
       -> {"results": [{"hits": [{"score","path","url","image_base64",...}]}]}
"""

import json
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_FILE = ROOT / "pixelrag_state.json"

_DEFAULT_BASE = os.environ.get("PIXELRAG_BASE_URL", "http://127.0.0.1:30001")

_HEALTH_CACHE = {"ts": 0.0, "data": None}
_HEALTH_TTL = 5.0


# ── runtime state (dynamic, no hardcoding) ─────────────────────────────────
def _read_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_state(patch):
    state = _read_state()
    state.update(patch)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def get_base_url():
    return _read_state().get("base_url") or _DEFAULT_BASE


def set_base_url(url):
    _write_state({"base_url": url.rstrip("/")})


# ── health / status ─────────────────────────────────────────────────────
def is_pixelrag_running():
    """Synchronous check - True if PixelRAG's /health endpoint responds."""
    try:
        r = httpx.get(f"{get_base_url()}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def health(use_cache=True):
    """Synchronous, cached health check used by /pixelrag/status."""
    now = time.time()
    if use_cache and _HEALTH_CACHE["data"] is not None and (now - _HEALTH_CACHE["ts"]) < _HEALTH_TTL:
        return _HEALTH_CACHE["data"]
    base = get_base_url()
    try:
        r = httpx.get(f"{base}/health", timeout=5)
        data = {"reachable": r.status_code == 200, "base_url": base, "status_code": r.status_code}
    except Exception as e:
        data = {"reachable": False, "base_url": base, "error": str(e)[:200]}
    _HEALTH_CACHE["ts"] = now
    _HEALTH_CACHE["data"] = data
    return data


def status():
    """Synchronous status used by /pixelrag/status."""
    h = health()
    index_built = (ROOT / "pixelrag_index").is_dir()
    return {
        "online": h.get("reachable", False),
        "base_url": get_base_url(),
        "index_built": index_built,
        "mode": "pixelrag_visual_rag" if h.get("reachable") else "text_rag_only",
    }


# ── search ──────────────────────────────────────────────────────────────
def search(query_text, n_docs=4, include_images=True, timeout=20):
    """
    Query PixelRAG's visual index. Returns a list of hit dicts on success,
    or None on ANY failure (offline, index not built, timeout, bad response)
    so callers can fall back to text RAG cleanly — never raises.

    Each hit (when found): {score, path, url, image_base64 (if requested),
    article_id, tile_index}.
    """
    base = get_base_url()
    payload = {
        "queries": [{"text": query_text}],
        "n_docs": n_docs,
        "include_images": include_images,
    }
    try:
        r = httpx.post(f"{base}/search", json=payload, timeout=timeout)
        if r.status_code != 200:
            print(f"  [PIXELRAG] HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None
        hits = results[0].get("hits") or []
        return hits or None
    except httpx.TimeoutException:
        print(f"  [PIXELRAG] Timeout after {timeout}s")
        return None
    except Exception as e:
        print(f"  [PIXELRAG] Error: {e}")
        return None


# ── compatibility stub ─────────────────────────────────────────────────
def clear_model_cache(agent_name=None):
    pass
