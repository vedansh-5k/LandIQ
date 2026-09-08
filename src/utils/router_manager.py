"""
router_manager.py  (from student's LLM Configurator — adapted for LandIQ)
-----------------
Manages a registry of LiteLLM Router instances.
Each named config (e.g. "landiq_default") gets its own Router with
priority-based fallback, RPM/TPM limits, and usage-based routing.

Used by:
  - /configs  routes (create/update/delete)
  - /llm/{name}/chat  route (actual LLM calls)
  - llm_factory.py (LandIQ agent calls, optional)
"""

import os
import glob
import json
import logging
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)

# Registry: full_name -> litellm.Router
_registry: Dict[str, object] = {}

# Config store: full_name -> config dict
_configs: Dict[str, dict] = {}


def build_router_for_config(config: dict):
    """
    Builds a LiteLLM Router for the given config dict and stores it.
    config must have: full_name, operations (dict of op -> list of model dicts),
    restrictions (tpm, rpm, tpr).
    """
    try:
        from litellm import Router
    except ImportError:
        logger.error("litellm not installed — run: pip install litellm")
        return

    from src.utils.db import get_db_connection, get_api_key_for_provider
    from src.utils.crypto import decrypt_secret

    full_name = config["full_name"]

    # Load global models for API key lookup (keys are stored encrypted —
    # decrypt here, once, rather than at every completion() call)
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM global_models")
            global_models = {}
            for r in c.fetchall():
                row = dict(r)
                if row.get("api_key"):
                    row["api_key"] = decrypt_secret(row["api_key"])
                global_models[row["litellm_model"]] = row
    except Exception:
        global_models = {}

    router_model_list = []
    operations = config.get("operations", {})
    restrictions = config.get("restrictions", {})

    for op, models in operations.items():
        if not models:
            continue
        internal_name = f"{full_name}::{op}"

        for m in models:
            litellm_model = m.get("litellm_model", "")
            gm = global_models.get(litellm_model, {})

            # Provider comes from the stored pool row if we have one, else
            # from the "<provider>/model" prefix already present on the
            # config's own model string (e.g. "groq/openai/gpt-oss-120b").
            provider = gm.get("provider") or (
                litellm_model.split("/", 1)[0] if "/" in litellm_model else ""
            )
            actual_model = litellm_model
            if provider and provider != "other" and "/" not in actual_model:
                actual_model = f"{provider}/{actual_model}"

            api_key = (
                gm.get("api_key")
                or (os.environ.get(m["api_key_env"]) if m.get("api_key_env") else None)
                or (get_api_key_for_provider(provider) if provider else None)
            )
            api_base = gm.get("api_base") or m.get("api_base")

            params = {"model": actual_model}
            if api_key:   params["api_key"]  = api_key
            if api_base:  params["api_base"] = api_base
            params["tpm"]   = m.get("tpm") or restrictions.get("tpm", 100000)
            params["rpm"]   = m.get("rpm") or restrictions.get("rpm", 60)
            params["order"] = m.get("priority", 1)

            router_model_list.append({
                "model_name":     internal_name,
                "litellm_params": params,
            })

    if not router_model_list:
        logger.warning(f"No models in router list for {full_name} — skipping")
        return

    # num_retries/timeout were 5/120 — stacked on top of dynamic_agent.py's own
    # 3x retry + Gemini fallback (already measured working this session), a
    # single agent could see up to 5x3=15 attempts and multi-minute hangs
    # before ever reaching that fallback. This router only needs to catch a
    # genuinely transient blip; dynamic_agent.py owns the real retry/fallback
    # logic now, so it doesn't need to duplicate that work.
    router = Router(
        model_list=router_model_list,
        num_retries=1,
        timeout=30,
        retry_after=2,
        routing_strategy="usage-based-routing-v2",
        enable_pre_call_checks=False,
        allowed_fails=10,
        cooldown_time=5,
    )

    _registry[full_name] = router
    _configs[full_name] = config
    logger.info(f"  [ROUTER] Built router for '{full_name}' with {len(router_model_list)} deployments.")


def evict_router(full_name: str):
    _registry.pop(full_name, None)
    _configs.pop(full_name, None)
    logger.info(f"  [ROUTER] Evicted '{full_name}'")


def get_router(full_name: str):
    return _registry.get(full_name)


def get_operations(full_name: str) -> Set[str]:
    if full_name not in _configs:
        return set()
    return set(_configs[full_name].get("operations", {}).keys())


def has_vision(full_name: str) -> bool:
    try:
        import litellm
    except ImportError:
        return False
    if full_name not in _configs:
        return False
    for m in _configs[full_name].get("operations", {}).get("chat", []):
        info = litellm.model_cost.get(m.get("litellm_model", ""), {})
        if info.get("supports_vision"):
            return True
    return False


def get_capabilities(full_name: str) -> dict:
    if full_name not in _configs:
        raise ValueError(f"Config '{full_name}' not found.")
    ops = list(get_operations(full_name))
    if has_vision(full_name):
        ops.append("vision")
    return {
        "operations": ops,
        "vision": has_vision(full_name),
        "endpoints": [f"/llm/{full_name}/{op}" for op in ops],
    }


def load_all_configs_on_startup(configs_dir: str):
    """
    Called at server startup — loads all active JSON configs and builds routers.
    """
    if not os.path.isdir(configs_dir):
        return
    files = glob.glob(os.path.join(configs_dir, "*.json"))
    loaded = 0
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fd:
                data = json.load(fd)
            if data.get("status") == "active":
                build_router_for_config(data)
                loaded += 1
        except Exception as e:
            logger.error(f"Failed to load config {f}: {e}")
    logger.info(f"  [ROUTER] Loaded {loaded} active configs on startup.")