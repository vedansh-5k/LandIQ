"""
financial/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_FINANCE
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import FinancialOutput
from src.graph.state import LandQueryState
from src.agents.financial.prompts import FINANCIAL_SYSTEM_PROMPT, FINANCIAL_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman



def run_financial_agent(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("financial", temperature=TEMP_FINANCE)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(FinancialOutput, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(FinancialOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(FINANCIAL_SYSTEM_PROMPT)),
            ("human", FINANCIAL_HUMAN_PROMPT)
        ])
        inputs = {"state": state["state"], "city": state["city"], "area": state["area"], "land_size": state["land_size"], "land_unit": state["land_unit"], "land_type": state["land_type"], "total_budget": state["total_budget"], "construction_budget": state.get("construction_budget", 0), "purpose": state["purpose"], "taking_loan": state.get("taking_loan", False), "loan_amount": state.get("loan_amount", 0), "loan_interest_rate": state.get("loan_interest_rate", 0), "timeline_years": state["timeline_years"], "monthly_income_expectation": state.get("monthly_income_expectation", 0), "rag_context": state.get("rag_context", "No context available.")}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Financial ROI Agent")
        return {"financial_output": response, "completed_agents": ["Financial ROI Agent"]}
    except Exception as e:
        print(f"  [FINANCIAL ERROR] {str(e)[:120]}")
        return {"error_log": [f"Financial ROI Agent failed: {str(e)}"], "completed_agents": ["Financial ROI Agent (Failed)"]}