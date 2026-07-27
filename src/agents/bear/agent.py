"""
bear/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_DEVIL
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import BearCaseOutput
from src.graph.state import LandQueryState
from src.agents.bear.prompts import BEAR_SYSTEM_PROMPT, BEAR_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman
from src.utils.toon import build_compact_context


def run_bear_agent(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("bear", temperature=TEMP_DEVIL)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(BearCaseOutput, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(BearCaseOutput)
        compact = build_compact_context(legal_output=state.get('legal_output'), financial_output=state.get('financial_output'), market_output=state.get('market_output'))
        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(BEAR_SYSTEM_PROMPT)),
            ("human", BEAR_HUMAN_PROMPT)
        ])
        inputs = {"city": state["city"], "area": state["area"], "state": state["state"], "land_size": state["land_size"], "land_unit": state["land_unit"], "total_budget": state["total_budget"], "purpose": state["purpose"], "timeline_years": state["timeline_years"], "legal_summary": compact, "financial_summary": "", "market_summary": ""}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Bear Case Agent")
        return {"bear_output": response, "completed_agents": ["Bear Case Agent"]}
    except Exception as e:
        print(f"  [BEAR ERROR] {str(e)[:120]}")
        return {"error_log": [f"Bear Case Agent failed: {str(e)}"], "completed_agents": ["Bear Case Agent (Failed)"]}