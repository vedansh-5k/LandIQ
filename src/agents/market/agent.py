"""
market/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_RISK
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import MarketOutput
from src.graph.state import LandQueryState
from src.agents.market.prompts import MARKET_SYSTEM_PROMPT, MARKET_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman



def run_market_agent(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("market", temperature=TEMP_RISK)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(MarketOutput, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(MarketOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(MARKET_SYSTEM_PROMPT)),
            ("human", MARKET_HUMAN_PROMPT)
        ])
        inputs = {"state": state["state"], "city": state["city"], "area": state["area"], "land_type": state["land_type"], "land_size": state["land_size"], "land_unit": state["land_unit"], "purpose": state["purpose"], "timeline_years": state["timeline_years"], "risk_tolerance": state["risk_tolerance"], "rag_context": state.get("rag_context", "No context available.")}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Market Intelligence Agent")
        return {"market_output": response, "completed_agents": ["Market Intelligence Agent"]}
    except Exception as e:
        print(f"  [MARKET ERROR] {str(e)[:120]}")
        return {"error_log": [f"Market Intelligence Agent failed: {str(e)}"], "completed_agents": ["Market Intelligence Agent (Failed)"]}