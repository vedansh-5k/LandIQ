"""
litellm_factory.py — WORKING FINAL
Gemini fix: with_structured_output(method="function_calling")
  - avoids responseMimeType and systemInstruction fields
  - these v1beta-specific fields cause 400 INVALID_ARGUMENT with AQ. keys
  - function_calling uses tool/function API which works on all Gemini versions
"""

import os
from src.utils.litellm_config import get_active_model
from src.utils.agent_configurator import get_agent_config

_runtime_keys: dict = {}


def set_runtime_key(provider: str, api_key: str):
    _runtime_keys[provider] = api_key
    print(f"  [LLM] Runtime key stored for {provider}")


def _key(env: str, provider: str) -> str:
    return _runtime_keys.get(provider, "") or os.getenv(env, "")


def get_llm_for_agent(agent_name: str, temperature: float = 0.3):
    agent_cfg  = get_agent_config(agent_name)
    final_temp = agent_cfg.get("temperature", temperature)
    active     = get_active_model()
    model_str  = active["litellm_model"]
    provider   = active["provider"]
    api_key    = _key(active["api_key_env"], provider)

    print(f"  [LLM] {agent_name} → {active['name']} ({provider}) | temp={final_temp}")

    if provider == "Groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            api_key=api_key,
            model=model_str.replace("groq/", ""),
            temperature=final_temp
        )

    if provider == "Google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError("Run: pip install langchain-google-genai")
        # NOTE: Do NOT set api_version here — let the SDK decide
        # NOTE: Do NOT set convert_system_message_to_human — not needed with function_calling
        # The structured_llm in each agent must use method="function_calling"
        # See: tracked_chain.py which handles this
        return ChatGoogleGenerativeAI(
            model=model_str.replace("gemini/", ""),
            google_api_key=api_key,
            temperature=final_temp,
            max_output_tokens=2048,
        )

    if provider == "Anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError("Run: pip install langchain-anthropic")
        return ChatAnthropic(
            model=model_str,
            anthropic_api_key=api_key,
            temperature=final_temp,
            max_tokens=2048
        )

    if provider == "OpenAI":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("Run: pip install langchain-openai")
        return ChatOpenAI(
            model=model_str,
            api_key=api_key,
            temperature=final_temp
        )

    if provider == "Mistral":
        try:
            from langchain_mistralai import ChatMistralAI
        except ImportError:
            raise ImportError("Run: pip install langchain-mistralai")
        return ChatMistralAI(
            model=model_str.replace("mistral/", ""),
            api_key=api_key,
            temperature=final_temp
        )

    try:
        from langchain_community.chat_models import ChatLiteLLM
        return ChatLiteLLM(model=model_str, api_key=api_key, temperature=final_temp)
    except Exception:
        pass

    print(f"  [LLM] Fallback → Groq Llama")
    from langchain_groq import ChatGroq
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY", ""),
        model="llama-3.3-70b-versatile",
        temperature=final_temp
    )