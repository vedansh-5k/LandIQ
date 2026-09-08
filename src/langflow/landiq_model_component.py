"""
landiq_model_component.py — "LandIQ Model" Langflow box (Config 1)
-----------------------------------------------------------------------------
PASTE THIS WHOLE FILE into a new Custom Component in Langflow's UI.
See the numbered steps Claude gave you in chat for exactly how.

WHAT THIS BOX IS:
This is Config 1 that sir asked for — "landiq_model". Type a prompt into this
box, hit Run, and it calls the REAL landiq_model config (Groq priority 1,
Gemini priority 2, with RPM/TPM guardrails) that already exists on the
backend, and shows you the real answer. Nothing here is simulated — it POSTs
to the exact same /test/{full_name} "test board" endpoint you already tested
from the terminal.

Follows the same house style as your existing "Orchestrator LLM" and
"PII Safety Guardrail" boxes already live in your flow: a thin wrapper that
calls the backend and returns the result. No new backend logic lives here.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.message import Message
import json

BACKEND_URL = "http://127.0.0.1:8000"


class LandIQModel(Component):
    display_name = "LandIQ Model"
    description = (
        "Config 1 — landiq_model. The LandIQ model pool: Groq tried first "
        "(priority 1), Gemini as fallback (priority 2), with RPM/TPM "
        "guardrails. Type any prompt and run this box standalone to chat/"
        "generate directly through it — this calls the real backend "
        "/test/{config} endpoint, not a simulation."
    )
    icon = "sparkles"
    name = "LandIQModel"

    inputs = [
        MessageTextInput(
            name="prompt",
            display_name="Prompt",
            value="Say hello and state your model name.",
            info="Whatever you type here is sent straight to landiq_model.",
        ),
        MessageTextInput(
            name="config_full_name",
            display_name="Config Name",
            value="landiq_model",
            info="Which named LLM config to use. Defaults to landiq_model.",
        ),
    ]

    outputs = [
        Output(display_name="Response", name="response", method="generate"),
        Output(display_name="Config Name", name="config_name_out", method="emit_config_name"),
    ]

    def emit_config_name(self) -> Message:
        """Passes this box's config name onward so it can be wired straight
        into LandIQ Agent Config's 'Config Name' field on the canvas — makes
        the "Config 2 uses Config 1" relationship a real, visible line
        instead of just two boxes that happen to share a typed-in name."""
        return Message(text=(self.config_full_name or "landiq_model").strip())

    def generate(self) -> Message:
        import httpx

        full_name = (self.config_full_name or "landiq_model").strip()
        prompt = self.prompt or ""

        try:
            r = httpx.post(
                f"{BACKEND_URL}/test/{full_name}",
                json={"prompt": prompt, "max_tokens": 512, "temperature": 0.3},
                timeout=60,
            )
            data = r.json()
        except Exception as e:
            msg = f"[landiq_model unreachable] {type(e).__name__}: {str(e)[:200]}"
            self.status = msg
            return Message(text=msg)

        self.status = data
        if data.get("success"):
            model_used = data.get("model_used", "?")
            tokens = data.get("total_tokens", "?")
            text = data.get("response", "")
            return Message(
                text=f"{text}\n\n— served by: {model_used} | tokens: {tokens} | config: {full_name}"
            )
        return Message(text=f"[landiq_model error] {json.dumps(data)[:300]}")
