# Check what get_llm_for_agent("orchestrator") returns
# This tells us if the orchestrator LLM call works or silently fails
import sys
sys.path.insert(0, '.')
try:
    from src.utils.llm_factory import get_llm_for_agent
    llm = get_llm_for_agent("orchestrator", temperature=0.1)
    print(f"LLM type: {type(llm).__name__}")
    print(f"LLM model: {getattr(llm, 'model_name', getattr(llm, 'model', 'unknown'))}")
    print("SUCCESS — orchestrator can get an LLM")
except Exception as e:
    print(f"FAILED: {e}")
    print("This is why the orchestrator silently falls back to default plan")
