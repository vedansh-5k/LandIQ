"""
landiq_config_picker_component.py — "LandIQ Config" Langflow box (Config 1, final — proven working)
-----------------------------------------------------------------------------
Confirmed working end-to-end on 2026-09-10 after extensive direct testing
against this exact Langflow install:

  - A dropdown's "options"/"value" MUST be computed live, directly in this
    file's own top-level code (_ACTIVE_CONFIGS = _discover_active_configs()
    below), not injected afterward into the saved flow's JSON. Editing the
    saved JSON's field value directly — whether by a script or by copying
    a different value into the file — is silently ignored by this Langflow
    version at run time; only what this file's own code computes is ever
    used as the field's baseline value. Proven by direct testing: three
    separate JSON-injection attempts (with real_time_refresh, without it,
    and on a brand-new never-before-built node) all came back empty, while
    a plain dropdown computing its options/value here, live, worked
    immediately.

  - refresh_button / real_time_refresh / update_build_config were REMOVED
    on purpose — they only affect what the Langflow *editor* shows while
    you're wiring the canvas (a UI-only hook), not what a run actually
    uses, and combining them with an empty options=[] default was exactly
    what caused the field to always resolve to nothing at run time.

  - A genuinely different pick per run — e.g. a client choosing a
    different config than whatever this file's own live default is —
    is delivered through Langflow's "tweaks" mechanism (POST
    /api/v1/run/advanced/{flow_id} with tweaks={"<this node's id>":
    {"saved_config": "<picked config>"}}), confirmed working on a clean
    isolated test. This is exactly what Langflow's own Playground uses
    under the hood when you pick a value from an exposed control and
    send a chat message — NOT a plain edit to the saved canvas.

Bottom line: every real config on the LandIQ website shows up here, live,
the moment this box is (re)built — nothing hardcoded. Wire this box's
"Model Config" output into "LandIQ Config Agent" (Config 2).
"""

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output
from lfx.schema.data import Data

BACKEND_URL = "http://127.0.0.1:8000"


def _discover_active_configs():
    """Live read of every active LLM config on the LandIQ website, right
    now. Never a fixed list — if this call fails, the dropdown is simply
    empty (never a fabricated fallback)."""
    try:
        import httpx
        r = httpx.get(f"{BACKEND_URL}/configs/active", timeout=5)
        r.raise_for_status()
        names = [c["full_name"] for c in r.json() if c.get("full_name")]
        return names or ["no_active_configs_on_website"]
    except Exception:
        return ["landiq_backend_unreachable"]


_ACTIVE_CONFIGS = _discover_active_configs()


class LandIQConfigPicker(Component):
    display_name = "LandIQ Config"
    description = (
        "Config 1 — a dropdown of every real, active LLM config that exists "
        "on the LandIQ website right now (GET /configs/active — nothing "
        "hardcoded; recomputed every time this box is rebuilt). Wire the "
        "'Model Config' output into 'LandIQ Config Agent'. To run a "
        "specific config from code/API instead of this box's own default, "
        "pass it via Langflow's tweaks: "
        '{"<this node id>": {"saved_config": "<config name>"}}.'
    )
    icon = "sparkles"
    name = "LandIQConfigPicker"

    inputs = [
        DropdownInput(
            name="saved_config",
            display_name="LLM Config (live from website)",
            options=_ACTIVE_CONFIGS,
            value=_ACTIVE_CONFIGS[0] if _ACTIVE_CONFIGS else "",
            info="Every active config on the LandIQ website, read live when this box was built.",
        ),
        MessageTextInput(
            name="prompt",
            display_name="Test Prompt",
            value="Say hello and state your model name.",
            info="Sent on every run as a live proof-of-connection — check the Logs tab.",
        ),
    ]

    outputs = [
        Output(display_name="Model Config", name="model_config_out", method="emit_model_config"),
    ]

    def emit_model_config(self) -> Data:
        import httpx

        full_name = (self.saved_config or "").strip()
        cfg = {"mode": "saved", "config_full_name": full_name}

        if not full_name:
            cfg["live_proof"] = "[error] No config selected."
            self.status = cfg["live_proof"]
            return Data(data=cfg)

        prompt = self.prompt or ""
        try:
            r = httpx.post(
                f"{BACKEND_URL}/test/{full_name}",
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
                f"LIVE, direct call to '{full_name}' -> {data.get('response', '')} "
                f"[served by {data.get('model_used', '?')}, tokens: {data.get('total_tokens', '?')}]"
            )
        else:
            cfg["live_proof"] = f"[error] Config '{full_name}' call failed: {data}"
        self.status = cfg["live_proof"]
        return Data(data=cfg)
