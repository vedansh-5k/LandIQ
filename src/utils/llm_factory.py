"""
llm_factory.py  —  FINAL (4 bugs fixed from terminal evidence)

BUG 1  token report empty ('NO CALLS RECORDED')
       _record_tokens called record_tokens / record_usage / record
       but tracked_chain.py exposes record_agent_tokens.
       FIX: call record_agent_tokens directly.

BUG 2  doc_summariser_LLM_config 400 Bad Request
       His config has tpr=1000 (max 1000 tokens per request).
       We sent max_tokens=4096. Server rejected it.
       FIX: read tpr from /configs, cap max_tokens to it.

BUG 3  gemini-2.0-flash 400 INVALID_ARGUMENT / 429 RESOURCE_EXHAUSTED
       The Google key works — gemini-flash-latest returned 'ok'.
       Wrong model ID was the problem.
       FIX: use gemini-flash-latest as the Gemini model.

BUG 4  agents die with no output when router/external/gemini fails
       FIX: every path falls back to direct ChatGroq.
"""

import os
import threading
import time
import json
from typing import Any, List, Optional, Dict
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.runnables import RunnableSerializable
from src.utils.llm_configurator import get_active_llm

_runtime_keys: dict = {}
_tls = threading.local()

GROQ_FALLBACK_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


# ═══════════════════════ helpers ══════════════════════════════════════

def set_runtime_key(provider, api_key):
    _runtime_keys[provider] = api_key

def set_active_external_config(config_name, base_url=None):
    _tls.external_config = config_name
    _tls.external_base = base_url or ""
    _tls.force_local = False

def clear_active_external_config():
    _tls.external_config = None
    _tls.external_base = None
    _tls.force_local = False

def set_active_config(config_name):
    _tls.selected_config = config_name

def clear_active_config():
    _tls.selected_config = None

def _is_forced_local():
    return bool(getattr(_tls, "force_local", False))


def _key(env_name, provider):
    key = _runtime_keys.get(provider, "") or os.getenv(env_name, "")
    if not key:
        try:
            from src.utils.db import get_db_connection
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT api_key FROM global_models WHERE provider=? "
                    "AND api_key IS NOT NULL AND api_key != '' LIMIT 1",
                    (provider,)).fetchone()
                if row:
                    key = row[0]
                    os.environ[env_name] = key
        except Exception:
            pass
    return key


def _convert_messages(messages):
    out = []
    for m in messages:
        if isinstance(m, tuple):
            role, content = m
        elif hasattr(m, "type"):
            role = {"system": "system", "ai": "assistant"}.get(m.type, "user")
            content = m.content
        else:
            role = m.get("role", "user")
            content = m.get("content", "")
        out.append({"role": role, "content": content})
    return out


def _usage_from(obj):
    if obj is None:
        return {}
    try:
        if not isinstance(obj, dict):
            obj = {"prompt_tokens": getattr(obj, "prompt_tokens", 0),
                   "completion_tokens": getattr(obj, "completion_tokens", 0),
                   "total_tokens": getattr(obj, "total_tokens", 0)}
        p = int(obj.get("prompt_tokens") or obj.get("input_tokens") or 0)
        c = int(obj.get("completion_tokens") or obj.get("output_tokens") or 0)
        return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}
    except Exception:
        return {}


def _ai_msg(content, usage, model_name):
    u = _usage_from(usage)
    kw = {"content": content}
    if u:
        kw["usage_metadata"] = {"input_tokens": u["prompt_tokens"],
                                "output_tokens": u["completion_tokens"],
                                "total_tokens": u["total_tokens"]}
        kw["response_metadata"] = {"token_usage": u, "model_name": model_name}
    try:
        return AIMessage(**kw)
    except Exception:
        return AIMessage(content=content)


# ═══════════════ BUG 1 FIX: call record_agent_tokens ═════════════════

def _record_tokens(agent_name, usage, provider="groq"):
    """Push into tracked_chain using the ACTUAL function name."""
    try:
        from src.utils.tracked_chain import record_agent_tokens
        u = _usage_from(usage)
        record_agent_tokens(
            agent_name,
            u.get("prompt_tokens", 0),
            u.get("completion_tokens", 0),
            provider=provider,
            exact=True,
        )
    except Exception as e:
        print("  [TOKENS] %s recording failed: %s" % (agent_name, str(e)[:80]))


def _is_rate_limit(err):
    s = str(err).lower()
    return ("rate limit" in s or "ratelimit" in s or "429" in s
            or "no deployments available" in s)


def _backoff(attempt, err):
    if _is_rate_limit(err):
        return [12, 20, 30][min(attempt, 2)]
    return [3, 6, 9][min(attempt, 2)]


# ═══════════════ SAFETY NET: direct Groq ═════════════════════════════

def _groq_direct(temperature=0.3, schema=None):
    key = _key("GROQ_API_KEY", "groq")
    if not key:
        return None
    try:
        from langchain_groq import ChatGroq
        llm = ChatGroq(api_key=key, model=GROQ_FALLBACK_MODEL,
                       temperature=temperature, max_retries=2)
        if schema is not None:
            return llm.with_structured_output(schema)
        return llm
    except Exception as e:
        print("  [FALLBACK] could not build Groq: %s" % str(e)[:80])
        return None


# ═══════════════ BUG 3 FIX: Gemini uses gemini-flash-latest ══════════

_GEMINI_FC_CLS = None

def _gemini_fc_class():
    global _GEMINI_FC_CLS
    if _GEMINI_FC_CLS is not None:
        return _GEMINI_FC_CLS
    from langchain_google_genai import ChatGoogleGenerativeAI

    class _GeminiFC(ChatGoogleGenerativeAI):
        def with_structured_output(self, schema, **kwargs):
            kwargs.setdefault("method", "function_calling")
            try:
                return super().with_structured_output(schema, **kwargs)
            except Exception:
                kwargs.pop("method", None)
                return super().with_structured_output(schema, **kwargs)

    _GEMINI_FC_CLS = _GeminiFC
    return _GEMINI_FC_CLS


# ═══════════════ BUG 2 FIX: external respects tpr cap ════════════════

EXTERNAL_TIMEOUT = int(os.getenv("EXTERNAL_LLM_TIMEOUT", "45"))
_EXT_HEADERS = {"Content-Type": "application/json",
                "Accept": "application/json",
                "X-Tunnel-Skip-Auth-Redirect": "true"}
_EXT_TPR_CACHE = {}   # config_name -> max tokens per request


def load_external_caps(config_name, base_url):
    """Read tpr from his /configs endpoint. Called once in pre-flight."""
    try:
        import requests
        r = requests.get(base_url.rstrip("/") + "/configs",
                         headers=_EXT_HEADERS, timeout=10)
        if r.status_code != 200:
            return
        arr = r.json()
        if isinstance(arr, dict):
            arr = arr.get("configs", [])
        for c in arr:
            if not isinstance(c, dict):
                continue
            name = c.get("full_name") or c.get("config_name") or c.get("name")
            rest = c.get("restrictions")
            if isinstance(rest, dict):
                tpr = rest.get("tpr") or rest.get("max_tokens_per_request")
                if isinstance(tpr, (int, float)) and tpr > 0:
                    _EXT_TPR_CACHE[name] = int(tpr)
                    if name == config_name:
                        print("  [EXTERNAL] '%s' token cap (tpr) = %d" % (name, int(tpr)))
    except Exception as e:
        print("  [EXTERNAL] cap lookup skipped: %s" % str(e)[:80])


def _ext_max_tokens(config_name):
    cap = _EXT_TPR_CACHE.get(config_name, 4096)
    return min(cap, 4096)


def _extract_content(data):
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return None
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        pass
    try:
        return data["choices"][0]["text"]
    except Exception:
        pass
    for k in ("response", "content", "output", "text", "result",
              "answer", "completion", "reply", "generated_text"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


class ExternalStudentChatModel(BaseChatModel):
    config_name: str
    base_url: str
    temperature: float = 0.3
    max_tokens: Optional[int] = 4096

    @property
    def _llm_type(self):
        return "external_student_server"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        import requests as _req
        lm = _convert_messages(messages)
        url = "%s/llm/%s/chat" % (self.base_url.rstrip("/"), self.config_name)
        mt = _ext_max_tokens(self.config_name)
        payload = {"messages": lm, "temperature": self.temperature, "max_tokens": mt}

        last_err = None
        for attempt in range(2):
            try:
                r = _req.post(url, json=payload, headers=_EXT_HEADERS,
                              timeout=EXTERNAL_TIMEOUT)
                if "html" in (r.headers.get("content-type") or ""):
                    raise RuntimeError("Tunnel login page - set Port Visibility Public")
                if r.status_code != 200:
                    raise RuntimeError("HTTP %s: %s" % (r.status_code,
                                       (r.text or "")[:250].replace("\n", " ")))
                data = r.json()
                content = _extract_content(data)
                if not content:
                    raise RuntimeError("200 but no content in: %s" % str(data)[:200])
                usage = data.get("usage")
                _record_tokens(self.config_name, usage, "external")
                msg = _ai_msg(content, usage,
                              data.get("model") or ("ext:" + self.config_name))
                return ChatResult(generations=[ChatGeneration(message=msg)])
            except Exception as e:
                last_err = e
                print("  [EXTERNAL %d/2] %s" % (attempt + 1, str(e)[:100]))
                if attempt < 1:
                    time.sleep(2)

        # BUG 4 FIX: fall back to Groq
        fb = _groq_direct(self.temperature)
        if fb is not None:
            print("  [FALLBACK] external -> DIRECT GROQ")
            try:
                out = fb.invoke(messages)
                _record_tokens(self.config_name + " (fallback)", 
                               getattr(out, "usage_metadata", None), "groq")
                return ChatResult(generations=[ChatGeneration(message=out)])
            except Exception as e2:
                print("  [FALLBACK] Groq also failed: %s" % str(e2)[:100])
        raise last_err

    def with_structured_output(self, schema, *, include_raw=False, **kwargs):
        return ExternalStructuredOutput(
            config_name=self.config_name, base_url=self.base_url,
            schema_to_validate=schema, temperature=self.temperature,
            max_tokens=self.max_tokens)


class ExternalStructuredOutput(RunnableSerializable[Any, Any]):
    config_name: str
    base_url: str
    schema_to_validate: Any
    temperature: float = 0.3
    max_tokens: Optional[int] = 4096

    @property
    def lc_serializable(self):
        return False

    def invoke(self, input, config=None, **kwargs):
        import requests as _req
        messages = input.to_messages() if hasattr(input, "to_messages") else input
        lm = _convert_messages(messages)

        schema_json = json.dumps(self.schema_to_validate.model_json_schema(), indent=2)
        instruction = ("\n\nYou MUST respond with ONLY a valid JSON object matching "
                       "this schema. No markdown, no backticks, no explanation:\n"
                       + schema_json)
        if lm and lm[0]["role"] == "system":
            lm[0]["content"] += instruction
        else:
            lm.insert(0, {"role": "system", "content": instruction})

        url = "%s/llm/%s/chat" % (self.base_url.rstrip("/"), self.config_name)
        mt = _ext_max_tokens(self.config_name)
        payload = {"messages": lm, "temperature": self.temperature, "max_tokens": mt}

        last_err = None
        for attempt in range(2):
            try:
                r = _req.post(url, json=payload, headers=_EXT_HEADERS,
                              timeout=EXTERNAL_TIMEOUT)
                if r.status_code != 200:
                    raise RuntimeError("HTTP %s: %s" % (r.status_code,
                                       (r.text or "")[:250].replace("\n", " ")))
                data = r.json()
                content = _extract_content(data)
                if not content:
                    raise RuntimeError("200 but no content")
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                if not content.startswith("{"):
                    s, e2 = content.find("{"), content.rfind("}")
                    if s != -1 and e2 > s:
                        content = content[s:e2 + 1]
                _record_tokens(self.config_name, data.get("usage"), "external")
                return self.schema_to_validate.model_validate_json(content)
            except Exception as e:
                last_err = e
                print("  [EXTERNAL-S %d/2] %s" % (attempt + 1, str(e)[:110]))
                if attempt < 1:
                    time.sleep(2)

        fb = _groq_direct(self.temperature, self.schema_to_validate)
        if fb is not None:
            print("  [FALLBACK] external structured -> DIRECT GROQ")
            try:
                return fb.invoke(messages)
            except Exception as e2:
                print("  [FALLBACK] Groq also failed: %s" % str(e2)[:100])
        raise last_err


# ═══════════════ LiteLLM Router models ═══════════════════════════════

class RouterStructuredOutputLLM(RunnableSerializable[Any, Any]):
    router: Any
    config_name: str
    schema_to_validate: Any
    temperature: float = 0.3
    max_tokens: Optional[int] = None

    @property
    def lc_serializable(self):
        return False

    def invoke(self, input, config=None, **kwargs):
        messages = input.to_messages() if hasattr(input, "to_messages") else input
        lm = _convert_messages(messages)
        schema_json = json.dumps(self.schema_to_validate.model_json_schema(), indent=2)
        instruction = ("\n\nYou MUST respond with a JSON object that strictly "
                       "adheres to this JSON Schema:\n" + schema_json)
        if lm and lm[0]["role"] == "system":
            lm[0]["content"] += instruction
        else:
            lm.insert(0, {"role": "system", "content": instruction})

        last_err = None
        for attempt in range(3):
            try:
                kwargs.pop("max_tokens", None)
                resp = self.router.completion(
                    model="%s::chat" % self.config_name, messages=lm,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens or 4096,
                    response_format={"type": "json_object"})
                content = resp.choices[0].message.content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                _record_tokens(self.config_name, getattr(resp, "usage", None), "router")
                return self.schema_to_validate.model_validate_json(content.strip())
            except Exception as e:
                last_err = e
                wait = _backoff(attempt, e)
                print("  [ROUTER-S %d/3] %s | wait %ds"
                      % (attempt + 1, str(e)[:100], wait))
                if attempt < 2:
                    time.sleep(wait)

        fb = _groq_direct(self.temperature, self.schema_to_validate)
        if fb is not None:
            print("  [FALLBACK] router structured -> DIRECT GROQ")
            try:
                return fb.invoke(messages)
            except Exception as e2:
                print("  [FALLBACK] Groq also failed: %s" % str(e2)[:100])
        raise last_err


class RouterChatModel(BaseChatModel):
    router: Any
    config_name: str
    temperature: float = 0.3
    max_tokens: Optional[int] = None

    @property
    def _llm_type(self):
        return "litellm_router"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        lm = _convert_messages(messages)
        last_err = None
        for attempt in range(3):
            try:
                kwargs.pop("max_tokens", None)
                resp = self.router.completion(
                    model="%s::chat" % self.config_name, messages=lm,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens or 4096, **kwargs)
                content = resp.choices[0].message.content
                _record_tokens(self.config_name, getattr(resp, "usage", None), "router")
                msg = _ai_msg(content, getattr(resp, "usage", None),
                              "router:" + self.config_name)
                return ChatResult(generations=[ChatGeneration(message=msg)])
            except Exception as e:
                last_err = e
                wait = _backoff(attempt, e)
                print("  [ROUTER %d/3] %s | wait %ds"
                      % (attempt + 1, str(e)[:90], wait))
                if attempt < 2:
                    time.sleep(wait)

        fb = _groq_direct(self.temperature)
        if fb is not None:
            print("  [FALLBACK] router -> DIRECT GROQ")
            try:
                out = fb.invoke(messages)
                return ChatResult(generations=[ChatGeneration(message=out)])
            except Exception as e2:
                print("  [FALLBACK] Groq also failed: %s" % str(e2)[:100])
        raise last_err

    def with_structured_output(self, schema, *, include_raw=False, **kwargs):
        return RouterStructuredOutputLLM(
            router=self.router, config_name=self.config_name,
            schema_to_validate=schema, temperature=self.temperature,
            max_tokens=self.max_tokens)


# ═══════════════ build functions ═════════════════════════════════════

def _build_external_llm(config_name, temperature):
    base = getattr(_tls, "external_base", "") or os.environ.get("EXTERNAL_LLM_BASE", "")
    base = (base or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("No external base URL set")
    print("  [LLM] External '%s' -> %s/llm/%s/chat | temp=%s | tpr=%s"
          % (config_name, base, config_name, temperature,
             _EXT_TPR_CACHE.get(config_name, "?")))
    return ExternalStudentChatModel(config_name=config_name, base_url=base,
                                    temperature=temperature, max_tokens=4096)


def _build_llm(model_entry, final_temp):
    provider = model_entry.get("provider", "groq").lower()
    model = model_entry["model"]

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(api_key=_key("GROQ_API_KEY", "groq"),
                        model=model, temperature=final_temp)

    if provider in ("google", "gemini"):
        gkey = _key("GOOGLE_API_KEY", "google")
        if not gkey:
            print("  [LLM] No GOOGLE_API_KEY -> Groq fallback")
            from langchain_groq import ChatGroq
            return ChatGroq(api_key=_key("GROQ_API_KEY", "groq"),
                            model=GROQ_FALLBACK_MODEL, temperature=final_temp)
        return _gemini_fc_class()(model=GEMINI_MODEL, google_api_key=gkey,
                                  temperature=final_temp)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model,
                             anthropic_api_key=_key("ANTHROPIC_API_KEY", "anthropic"),
                             temperature=final_temp, max_tokens=2048)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=_key("OPENAI_API_KEY", "openai"),
                          temperature=final_temp)

    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(model=model, api_key=_key("MISTRAL_API_KEY", "mistral"),
                             temperature=final_temp)

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=_key("DEEPSEEK_API_KEY", "deepseek"),
                          base_url="https://api.deepseek.com/v1", temperature=final_temp)

    print("  [LLM] '%s' unknown -> Groq fallback" % provider)
    from langchain_groq import ChatGroq
    return ChatGroq(api_key=_key("GROQ_API_KEY", "groq"),
                    model=GROQ_FALLBACK_MODEL, temperature=final_temp)


def get_local_fallback_llm(temperature=0.3, schema=None):
    fb = _groq_direct(temperature, schema)
    if fb is not None:
        return fb
    gg = _key("GOOGLE_API_KEY", "google")
    if gg:
        llm = _gemini_fc_class()(model=GEMINI_MODEL, google_api_key=gg,
                                 temperature=temperature)
        return llm.with_structured_output(schema) if schema else llm
    raise RuntimeError("No usable local API key")


def get_llm_for_agent(agent_name, temperature=0.3):
    try:
        from src.utils.agent_configurator import get_agent_config
        final_temp = get_agent_config(agent_name).get("temperature", temperature)
    except Exception:
        final_temp = temperature

    forced_local = _is_forced_local()

    # external config
    ext_config = getattr(_tls, "external_config", None)
    if ext_config and not forced_local:
        try:
            from src.utils.router_manager import _configs
            cfg = _configs.get(ext_config, {})
            if cfg.get("_external"):
                print("  [LLM] %s -> EXTERNAL '%s' | temp=%s"
                      % (agent_name, ext_config, final_temp))
                return _build_external_llm(ext_config, final_temp)
        except Exception as e:
            print("  [LLM] External check failed: %s -> local" % e)
    elif ext_config and forced_local:
        print("  [LLM] %s -> '%s' SKIPPED (gateway offline)" % (agent_name, ext_config))

    # local LiteLLM router config
    selected_config = getattr(_tls, "selected_config", None)
    if selected_config and not forced_local:
        try:
            from src.utils.router_manager import get_router
            router = get_router(selected_config)
            if router:
                print("  [LLM] %s -> '%s' via Router | temp=%s"
                      % (agent_name, selected_config, final_temp))
                return RouterChatModel(router=router, config_name=selected_config,
                                       temperature=final_temp)
        except Exception as e:
            print("  [LLM] Router check failed: %s -> default" % e)

    # normal local
    active = get_active_llm()
    primary_id = active["id"]
    try:
        from src.utils.model_router import resolve
        actual_id = resolve(primary_id, agent_name)
    except Exception:
        actual_id = primary_id

    if actual_id != primary_id:
        from src.utils.llm_configurator import _by_id
        model_entry = _by_id(actual_id) or active
    else:
        model_entry = active

    print("  [LLM] %s -> %s (%s) | temp=%s"
          % (agent_name, model_entry["name"], model_entry["provider"], final_temp))
    return _build_llm(model_entry, final_temp)