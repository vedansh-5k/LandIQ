"""
landiq_priority_fallback_component.py — "LandIQ Priority Fallback" (Langflow box)
-----------------------------------------------------------------------------
Makes "priority 1 model, priority 2 model" a real, visible two-box wiring
on the canvas: wire one "LandIQ Model" box's "Model Config" output into
Primary, wire a second one into Fallback, and this box just passes both
through together. Deciding which one actually answers happens in the real
agent call (dynamic_agent.py already retries on the fallback if the
primary call fails) — this box's only job is to be the visible junction
point for "these two models, in this order," instead of a single dropdown
hiding that choice.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import HandleInput, Output
from lfx.schema.data import Data


class LandIQPriorityFallback(Component):
    display_name = "LandIQ Priority Fallback"
    description = (
        "Config 1, priority chain. Wire two 'LandIQ Model' boxes in here — "
        "Primary (priority 1) and Fallback (priority 2). Wire this box's "
        "output into 'LandIQ Agent Config' so the agent tries Primary first "
        "and only falls back to the second model if Primary genuinely fails."
    )
    icon = "shuffle"
    name = "LandIQPriorityFallback"

    inputs = [
        HandleInput(name="primary", display_name="Primary (priority 1)", input_types=["Data"]),
        HandleInput(name="fallback", display_name="Fallback (priority 2)", input_types=["Data"], required=False),
    ]

    outputs = [
        Output(display_name="Model Chain", name="chain_out", method="build_chain"),
    ]

    def build_chain(self) -> Data:
        primary = getattr(self.primary, "data", None) if self.primary is not None else None
        fallback = getattr(self.fallback, "data", None) if self.fallback is not None else None
        out = {"primary": primary, "fallback": fallback}
        self.status = {
            "primary": (primary or {}).get("model"),
            "fallback": (fallback or {}).get("model") if fallback else None,
        }
        return Data(data=out)
