"""
bull/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_ADVOCATE
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import BullCaseOutput
from src.graph.state import LandQueryState
from src.agents.bull.prompts import BULL_SYSTEM_PROMPT, BULL_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman
from src.utils.toon import build_compact_context


def run_bull_agent(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("bull", temperature=TEMP_ADVOCATE)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(BullCaseOutput, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(BullCaseOutput)
        compact = build_compact_context(location_output=state.get('location_output'), financial_output=state.get('financial_output'), market_output=state.get('market_output'))
        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(BULL_SYSTEM_PROMPT)),
            ("human", BULL_HUMAN_PROMPT)
        ])
        inputs = {"city": state["city"], "area": state["area"], "state": state["state"], "land_size": state["land_size"], "land_unit": state["land_unit"], "total_budget": state["total_budget"], "purpose": state["purpose"], "timeline_years": state["timeline_years"], "location_summary": compact, "financial_summary": "", "market_summary": ""}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Bull Case Agent")
        return {"bull_output": response, "completed_agents": ["Bull Case Agent"]}
    except Exception as e:
        print(f"  [BULL ERROR] {str(e)[:120]}")
        return {"error_log": [f"Bull Case Agent failed: {str(e)}"], "completed_agents": ["Bull Case Agent (Failed)"]}