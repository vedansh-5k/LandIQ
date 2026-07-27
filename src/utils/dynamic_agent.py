"""
dynamic_agent.py
----------------
THE UNIVERSAL AGENT RUNNER.

There are no more per-agent Python files. This ONE file can become ANY agent:
  1. Loads the agent's definition (AGENT.md + SKILL.md) via agent_loader
  2. Builds the Pydantic output schema AT RUNTIME with pydantic.create_model()
  3. Builds the prompt: AGENT.md body (WHO) + SKILL.md body (HOW) + user data
  4. Calls the LLM with structured output (Gemini-safe)
  5. Returns {agent_name}_output into the shared state

Adding a new agent = adding two .md files. Zero Python changes.
"""

import logging
from typing import List
from pydantic import Field, create_model

from src.utils.agent_loader import load_agent
from src.utils.llm_factory import get_llm_for_agent
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

# Cache runtime-built Pydantic models so we don't rebuild every call
_model_cache = {}

_TYPE_MAP = {
    "str":   (str, ""),
    "int":   (int, 0),
    "float": (float, 0.0),
    "bool":  (bool, False),
}


def build_output_model(agent_def: dict):
    """
    Turns the output_fields list from AGENT.md into a real Pydantic class,
    AT RUNTIME, using pydantic.create_model().

    AGENT.md frontmatter like:
        output_fields:
          - {name: area_overview, type: str, description: "Overview"}
          - {name: location_score, type: int, description: "Score 0-100"}
          - {name: red_flags, type: list, description: "Red flags found"}

    becomes the equivalent of a hand-written class:
        class LocationOutput(BaseModel):
            area_overview: str = Field(default="", description="Overview")
            location_score: int = Field(default=0, description="Score 0-100")
            red_flags: List[str] = Field(default_factory=list, description="...")

    Every field has a SAFE DEFAULT -> an LLM omitting a field never crashes
    validation (same fix that solved the DueDiligence 400 error).
    """
    name = agent_def["name"]
    if name in _model_cache:
        return _model_cache[name]

    fields = {}
    for f in agent_def.get("output_fields", []):
        fname = f.get("name")
        ftype = (f.get("type") or "str").lower()
        fdesc = f.get("description", "")
        if not fname:
            continue
        if ftype == "list":
            fields[fname] = (List[str], Field(default_factory=list, description=fdesc))
        else:
            py_type, default = _TYPE_MAP.get(ftype, (str, ""))
            fields[fname] = (py_type, Field(default=default, description=fdesc))

    if not fields:  # safety net: agent with no declared fields still works
        fields["summary"] = (str, Field(default="", description="Analysis summary"))

    Model = create_model(f"{name.title().replace('_','')}Output", **fields)
    _model_cache[name] = Model
    return Model


def clear_model_cache(agent_name: str = None):
    """Called when an agent is edited/deleted at runtime so its schema rebuilds."""
    if agent_name:
        _model_cache.pop(agent_name, None)
    else:
        _model_cache.clear()


def _build_human_prompt(agent_def: dict, state: dict) -> str:
    """
    Builds the data block every agent receives: property details,
    RAG context, and (for layer 2+) compact previous-agent outputs.
    """
    lines = [
        "PROPERTY DETAILS:",
        f"- Location: {state.get('area','')}, {state.get('city','')}, {state.get('state','')}",
        f"- Pincode: {state.get('pincode','') or 'not provided'}",
        f"- Land: {state.get('land_size','')} {state.get('land_unit','')} ({state.get('land_type','')})",
        f"- Title deed available: {state.get('has_title_deed','')}",
        f"- Total budget: INR {state.get('total_budget','')}",
        f"- Purpose: {state.get('purpose','')} | Timeline: {state.get('timeline_years','')} years",
        f"- Risk tolerance: {state.get('risk_tolerance','')}",
    ]
    if state.get("taking_loan"):
        lines.append(f"- Loan: INR {state.get('loan_amount',0)} at {state.get('loan_interest_rate',0)}%")
    if state.get("monthly_income_expectation"):
        lines.append(f"- Monthly income expectation: INR {state.get('monthly_income_expectation')}")

    lines.append("")
    lines.append("KNOWLEDGE BASE CONTEXT (Indian land market):")
    lines.append(str(state.get("rag_context", "No context available")))

    # Layer 2+ agents get compact summaries of earlier outputs
    if int(agent_def.get("layer", 1)) >= 2:
        try:
            from src.utils.toon import build_compact_context
            compact = build_compact_context(
                location_output=state.get("location_output"),
                legal_output=state.get("legal_output"),
                financial_output=state.get("financial_output"),
                market_output=state.get("market_output"),
                bull_output=state.get("bull_output"),
                bear_output=state.get("bear_output"),
            )
            if compact:
                lines.append("")
                lines.append("PREVIOUS AGENT FINDINGS (compact):")
                lines.append(str(compact))
        except Exception:
            pass

    lines.append("")
    lines.append("Produce your analysis now, filling EVERY field of your output schema.")
    return "\n".join(lines)


def run_dynamic_agent(agent_name: str, state: dict) -> dict:
    """
    THE UNIVERSAL ENTRYPOINT. The orchestrator calls this with any agent name.
    Returns {"{agent_name}_output": <pydantic obj>, "completed_agents": [...]}.
    """
    display = agent_name
    try:
        agent_def = load_agent(agent_name)
        if not agent_def:
            raise ValueError(f"Agent '{agent_name}' not found in agents_registry/")
        display = agent_def["display_name"]

        # 1. Runtime schema
        OutputModel = build_output_model(agent_def)

        # 2. Brain — created INSIDE the function so model switching works live
        llm = get_llm_for_agent(agent_name, temperature=agent_def["temperature"])

        # 3. Gemini-safe structured output
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(OutputModel, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(OutputModel)

        # 4. Prompt = WHO (AGENT.md body) + HOW (SKILL.md body) + caveman + data
        system_text = agent_def["agent_body"]
        if agent_def.get("skill_body"):
            system_text += "\n\n## YOUR WORKFLOW (follow these steps)\n" + agent_def["skill_body"]
        system_text = inject_caveman(system_text)

        human_text = _build_human_prompt(agent_def, state)

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_text),
            ("human", "{payload}"),
        ])

        response = run_tracked_chain(
            llm, structured_llm, prompt, {"payload": human_text}, display
        )

        return {
            f"{agent_name}_output": response,
            "completed_agents": [display],
        }

    except Exception as e:
        logger.error(f"[DYNAMIC AGENT ERROR] {agent_name}: {str(e)[:150]}")
        return {
            "error_log": [f"{display} failed: {str(e)}"],
            "completed_agents": [f"{display} (Failed)"],
        }