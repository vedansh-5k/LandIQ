"""
legal/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_COMPLIANCE
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import LegalOutput
from src.graph.state import LandQueryState
from src.agents.legal.prompts import LEGAL_SYSTEM_PROMPT, LEGAL_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman



def run_legal_agent(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("legal", temperature=TEMP_COMPLIANCE)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(LegalOutput, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(LegalOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(LEGAL_SYSTEM_PROMPT)),
            ("human", LEGAL_HUMAN_PROMPT)
        ])
        inputs = {"state": state["state"], "city": state["city"], "area": state["area"], "land_type": state["land_type"], "land_size": state["land_size"], "land_unit": state["land_unit"], "has_title_deed": state["has_title_deed"], "purpose": state["purpose"], "rag_context": state.get("rag_context", "No context available.")}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Legal and Title Agent")
        return {"legal_output": response, "completed_agents": ["Legal and Title Agent"]}
    except Exception as e:
        print(f"  [LEGAL ERROR] {str(e)[:120]}")
        return {"error_log": [f"Legal and Title Agent failed: {str(e)}"], "completed_agents": ["Legal and Title Agent (Failed)"]}