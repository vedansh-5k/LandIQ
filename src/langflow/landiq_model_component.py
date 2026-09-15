"""
landiq_model_component.py — "LandIQ Model" Langflow box (Config 1, v4 — final)
-----------------------------------------------------------------------------
ONE box, holding the full priority chain, exactly as originally described:
priority 1 model, priority 2 model, both real fields anyone can edit —
provider, model name, and (optional) their own API key. No backend
lookup, no saved config name, no database. This box's own fields ARE the
config.

Single output, on purpose (this Langflow install only lets a multi-output
custom component show one active connector at a time — a second output
already broke a wire once; never doing that again). The one output is a
Data object: {"primary": {provider, model, api_key}, "fallback": {...} or
None} — wire this straight into "LandIQ Agent Config".

Every run also makes a REAL, direct call to priority 1's provider (Groq or
Gemini's own REST API, never the LandIQ backend) and writes the real
answer into this component's status (visible in the Logs tab) — live
proof this box works with zero backend dependency, every single time it
runs, without needing a second output to view it.

Priority 2 is entirely optional — leave its fields blank and only
priority 1 gets wired through; dynamic_agent.py already knows to fall
back to priority 2 only if priority 1 can't be built at all (e.g. no key
available for it).
"""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output
from lfx.schema.data import Data
import os

PROJECT_ROOT = r"C:\Users\HP\OneDrive\Desktop\ai_boardroom_v3"

DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-flash-latest",
}


def _read_env_key(var_name: str) -> str:
    """Same direct-.env-read technique orchestrator_component_v2.py already
    uses, so this box still works out of the box with no key typed in."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.isfile(env_path):
        return ""
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() == var_name:
                    return v.strip().strip('"').strip("'")
    return ""


def _resolve_key(provider: str, typed_key: str) -> str:
    typed_key = (typed_key or "").strip()
    if typed_key:
        return typed_key
    env_var = "GROQ_API_KEY" if provider == "groq" else "GOOGLE_API_KEY"
    return _read_env_key(env_var)


class LandIQModel(Component):
    display_name = "LandIQ Model"
    description = (
        "Config 1 — landiq_model. One box, real priority chain: pick "
        "priority 1's provider/model/(optional) key, and optionally a "
        "priority 2 as well. Every run makes a REAL direct call to "
        "priority 1's provider — never the LandIQ backend — so the Logs "
        "tab proves it's genuinely live. Outputs one Data object, wire it "
        "straight into 'LandIQ Agent Config'. Bring your own key/model — "
        "any client can fill these fields with their own account."
    )
    icon = "sparkles"
    name = "LandIQModel"

    inputs = [
        DropdownInput(
            name="provider_1",
            display_name="Priority 1 — Provider",
            options=["groq", "gemini"],
            value="groq",
        ),
        MessageTextInput(
            name="model_1",
            display_name="Priority 1 — Model",
            value=DEFAULT_MODELS["groq"],
            info="e.g. openai/gpt-oss-120b (Groq) or gemini-flash-latest (Gemini).",
        ),
        MessageTextInput(
            name="api_key_1",
            display_name="Priority 1 — API Key (optional)",
            value="",
            info="Paste your own key. Leave blank to use this project's default key.",
        ),
        DropdownInput(
            name="provider_2",
            display_name="Priority 2 — Provider (optional)",
            options=["", "groq", "gemini"],
            value="gemini",
        ),
        MessageTextInput(
            name="model_2",
            display_name="Priority 2 — Model",
            value=DEFAULT_MODELS["gemini"],
            info="Used only if Priority 1 can't be built (e.g. no key available for it).",
        ),
        MessageTextInput(
            name="api_key_2",
            display_name="Priority 2 — API Key (optional)",
            value="",
            info="Paste your own key. Leave blank to use this project's default key.",
        ),
        MessageTextInput(
            name="prompt",
            display_name="Test Prompt",
            value="Say hello and state your model name.",
            info="Sent to Priority 1 on every run as a live proof-of-connection — check the Logs tab.",
        ),
    ]

    outputs = [
        Output(display_name="Model Config", name="model_config_out", method="emit_model_config"),
    ]

    def emit_model_config(self) -> Data:
        import httpx

        p1_provider = self.provider_1
        p1_model = (self.model_1 or DEFAULT_MODELS.get(p1_provider, "")).strip()
        p1_typed_key = (self.api_key_1 or "").strip()

        p2_provider = (self.provider_2 or "").strip()
        p2_model = (self.model_2 or "").strip()
        p2_typed_key = (self.api_key_2 or "").strip()

        # SECURITY: the wire/output only ever carries a key the user typed
        # themselves. When the field is left blank, the output's api_key
        # stays empty — dynamic_agent.py already falls back to its own
        # GROQ_API_KEY/GOOGLE_API_KEY env var server-side in that case, so
        # nothing changes functionally, but this project's own secret key
        # never gets embedded in something visible on screen or wired
        # across the canvas.
        primary = {"provider": p1_provider, "model": p1_model, "api_key": p1_typed_key}
        fallback = (
            {"provider": p2_provider, "model": p2_model, "api_key": p2_typed_key}
            if p2_provider and p2_model else None
        )
        cfg = {"primary": primary, "fallback": fallback}

        # The live test call below still needs a real key to prove the
        # connection works out of the box — resolved separately, used only
        # for this one call, never written into cfg/the wire/self.status.
        p1_key = p1_typed_key or _resolve_key(p1_provider, "")

        if not p1_key:
            self.status = (
                f"[landiq_model] No API key available for Priority 1 ('{p1_provider}') "
                f"— type one in, or check .env. Wiring still passes through."
            )
            return Data(data=cfg)

        prompt = self.prompt or ""
        try:
            if p1_provider == "groq":
                r = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {p1_key}", "Content-Type": "application/json"},
                    json={
                        "model": p1_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 512,
                        # Reasoning models (e.g. openai/gpt-oss-120b) spend part of
                        # max_tokens on invisible chain-of-thought before writing the
                        # visible answer — low keeps most of the budget free for the
                        # actual answer. Same fix already used in api.py's /test board.
                        "reasoning_effort": "low",
                    },
                    timeout=45,
                )
                r.raise_for_status()
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", "?")
            else:  # gemini
                r = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{p1_model}:generateContent?key={p1_key}",
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
                    },
                    timeout=45,
                )
                r.raise_for_status()
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                tokens = data.get("usageMetadata", {}).get("totalTokenCount", "?")
        except Exception as e:
            # Gemini's REST API takes the key as a URL query param, and some
            # httpx exceptions embed the request URL in their message — strip
            # the real key out before this ever reaches the screen.
            safe_err = str(e)[:250].replace(p1_key, "***")
            self.status = f"[landiq_model error on Priority 1] {type(e).__name__}: {safe_err}"
            return Data(data=cfg)

        fallback_note = f"{p2_provider}/{p2_model}" if fallback else "(none set)"
        self.status = (
            f"LIVE PROOF — direct call to Priority 1, no backend involved:\n{text}\n\n"
            f"served by: {p1_provider}/{p1_model} | tokens: {tokens}\n"
            f"Priority 1 -> {p1_provider}/{p1_model} (key: {'typed' if self.api_key_1.strip() else 'project default'})\n"
            f"Priority 2 -> {fallback_note}"
        )
        return Data(data=cfg)
    