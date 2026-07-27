"""
senior_consultant/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_SENIOR
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import FinalRecommendation
from src.graph.state import LandQueryState
from src.agents.senior_consultant.prompts import SENIOR_CONSULTANT_SYSTEM_PROMPT, SENIOR_CONSULTANT_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman
from src.utils.toon import build_compact_context


def run_senior_consultant(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("senior_consultant", temperature=TEMP_SENIOR)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(FinalRecommendation, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(FinalRecommendation)
        compact = build_compact_context(location_output=state.get('location_output'), legal_output=state.get('legal_output'), financial_output=state.get('financial_output'), market_output=state.get('market_output'), bull_output=state.get('bull_output'), bear_output=state.get('bear_output'), dd_output=state.get('due_diligence_output'))
        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(SENIOR_CONSULTANT_SYSTEM_PROMPT)),
            ("human", SENIOR_CONSULTANT_HUMAN_PROMPT)
        ])
        inputs = {"land_size": state["land_size"], "land_unit": state["land_unit"], "land_type": state["land_type"], "area": state["area"], "city": state["city"], "state": state["state"], "total_budget": state["total_budget"], "purpose": state["purpose"], "timeline_years": state["timeline_years"], "location_summary": compact, "legal_summary": "", "financial_summary": "", "market_summary": "", "bull_summary": "", "bear_summary": "", "dd_summary": ""}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Senior Consultant")
        return {"final_recommendation": response, "completed_agents": ["Senior Consultant"]}
    except Exception as e:
        print(f"  [SENIOR_CONSULTANT ERROR] {str(e)[:120]}")
        return {"error_log": [f"Senior Consultant failed: {str(e)}"], "completed_agents": ["Senior Consultant (Failed)"]}