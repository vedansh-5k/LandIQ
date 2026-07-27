"""
location/agent.py — multi-provider safe (Groq, Gemini, etc.)
"""

from langchain_core.prompts import ChatPromptTemplate
from src.utils.config import TEMP_GROWTH
from src.utils.llm_factory import get_llm_for_agent
from src.schemas.outputs import LocationOutput
from src.graph.state import LandQueryState
from src.agents.location.prompts import LOCATION_SYSTEM_PROMPT, LOCATION_HUMAN_PROMPT
from src.utils.tracked_chain import run_tracked_chain
from src.utils.caveman_mode import inject_caveman



def run_location_agent(state: LandQueryState) -> dict:
    try:
        llm = get_llm_for_agent("location", temperature=TEMP_GROWTH)

        # Gemini-safe structured output (avoids responseMimeType 400 error)
        if "GoogleGenerativeAI" in type(llm).__name__:
            structured_llm = llm.with_structured_output(LocationOutput, method="function_calling")
        else:
            structured_llm = llm.with_structured_output(LocationOutput)

        prompt = ChatPromptTemplate.from_messages([
            ("system", inject_caveman(LOCATION_SYSTEM_PROMPT)),
            ("human", LOCATION_HUMAN_PROMPT)
        ])
        inputs = {"state": state["state"], "city": state["city"], "area": state["area"], "land_size": state["land_size"], "land_unit": state["land_unit"], "land_type": state["land_type"], "purpose": state["purpose"], "timeline_years": state["timeline_years"], "rag_context": state.get("rag_context", "No context available.")}
        response = run_tracked_chain(llm, structured_llm, prompt, inputs, "Location Intelligence Agent")
        return {"location_output": response, "completed_agents": ["Location Intelligence Agent"]}
    except Exception as e:
        print(f"  [LOCATION ERROR] {str(e)[:120]}")
        return {"error_log": [f"Location Intelligence Agent failed: {str(e)}"], "completed_agents": ["Location Intelligence Agent (Failed)"]}