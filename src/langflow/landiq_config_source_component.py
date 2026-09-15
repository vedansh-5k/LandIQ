"""
landiq_config_source_component.py — "LandIQ Config: <name>" Langflow boxes (Config 1, final)
-----------------------------------------------------------------------------
Why this exists: every previous version of Config 1 asked the user to EDIT
a field (a dropdown, then a typed text field) to choose which saved
LandIQ config to use — and in this specific Langflow installation, edits
to a field inside a custom component do not reliably reach the component
when it runs (proven repeatedly: changing the field's own built-in
default changes the result, but editing it live on the canvas never
does, for either field type). Wires between boxes, on the other hand,
have worked correctly every single time today.

So this box has NOTHING to edit for the config choice. There are four
of them on the canvas — one fixed to "landiq_model", one to "land_alt",
one to "demo_test1", one to "land_plus" (the four configs that exist on
the LandIQ website right now). You choose which one to use by wiring
THAT box into "LandIQ Config Agent" — a real, physical, visible choice
on the canvas, which is actually a more literal form of "real wiring"
than a dropdown ever was.

CONFIG_NAME is the only thing that differs between the four pushed
copies of this file.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.data import Data

BACKEND_URL = "http://127.0.0.1:8000"
CONFIG_NAME = "landiq_model"  # <-- the only line that differs per instance


class LandIQConfigSource(Component):
    display_name = f"LandIQ Config: {CONFIG_NAME}"
    description = (
        f"Config 1 — fixed to the real, saved '{CONFIG_NAME}' LandIQ website "
        "config. Wire this box's output into 'LandIQ Config Agent' to use "
        f"'{CONFIG_NAME}'. To use a different config instead, wire in one of "
        "the other three 'LandIQ Config: ...' boxes instead — nothing to "
        "type or select, just pick which box you connect."
    )
    icon = "sparkles"
    name = "LandIQConfigSource"

    inputs = [
        MessageTextInput(
            name="prompt",
            display_name="Test Prompt",
            value="Say hello and state your model name.",
            info="Sent on every run as a live proof-of-connection — check the Outputs tab.",
        ),
    ]

    outputs = [
        Output(display_name="Model Config", name="model_config_out", method="emit_model_config"),
    ]

    def emit_model_config(self) -> Data:
        import httpx

        cfg = {"mode": "saved", "config_full_name": CONFIG_NAME}
        prompt = self.prompt or ""

        try:
            r = httpx.post(
                f"{BACKEND_URL}/test/{CONFIG_NAME}",
                json={"prompt": prompt, "max_tokens": 512, "temperature": 0.3},
                timeout=45,
            )
            data = r.json()
        except Exception as e:
            cfg["live_proof"] = f"[error] {type(e).__name__}: {str(e)[:250]}"
            self.status = cfg["live_proof"]
            return Data(data=cfg)

        if data.get("success"):
            cfg["live_proof"] = (
                f"LIVE, direct call to '{CONFIG_NAME}' -> {data.get('response', '')} "
                f"[served by {data.get('model_used', '?')}, tokens: {data.get('total_tokens', '?')}]"
            )
        else:
            cfg["live_proof"] = f"[error] Config '{CONFIG_NAME}' call failed: {data}"
        self.status = cfg["live_proof"]
        return Data(data=cfg)
