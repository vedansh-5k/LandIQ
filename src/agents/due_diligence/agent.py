"""
due_diligence/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_FACTCHECK
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import DueDiligenceOutput
from src.graph.state import LandQueryState
from src.agents.due_diligence.prompts import DD_SYSTEM_PROMPT, DD_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman
from src.utils.toon import build_compact_context


def run_due_diligence_agent(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("due_diligence", temperature=TEMP_FACTCHECK)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(DueDiligenceOutput, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(DueDiligenceOutput)
        compact = build_compact_context(location_output=state.get('location_output'), legal_output=state.get('legal_output'), financial_output=state.get('financial_output'), market_output=state.get('market_output'), bull_output=state.get('bull_output'), bear_output=state.get('bear_output'))
        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(DD_SYSTEM_PROMPT)),
            ("human", DD_HUMAN_PROMPT)
        ])
        inputs = {"land_size": state["land_size"], "land_unit": state["land_unit"], "area": state["area"], "city": state["city"], "state": state["state"], "total_budget": state["total_budget"], "location_summary": compact, "legal_summary": "", "financial_summary": "", "market_summary": "", "bull_summary": "", "bear_summary": ""}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Due Diligence Agent")
        return {"due_diligence_output": response, "completed_agents": ["Due Diligence Agent"]}
    except Exception as e:
        print(f"  [DUE_DILIGENCE ERROR] {str(e)[:120]}")
        return {"error_log": [f"Due Diligence Agent failed: {str(e)}"], "completed_agents": ["Due Diligence Agent (Failed)"]}