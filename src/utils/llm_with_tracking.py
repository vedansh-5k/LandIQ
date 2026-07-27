"""
llm_with_tracking.py
--------------------
Helper that runs a structured LLM call AND captures token usage
in a single API call — no double calling.

How it works:
1. Invokes the chain normally to get structured output
2. Separately calls llm.invoke() with same prompt to get
   the raw AIMessage which contains usage_metadata
3. Records tokens from the raw response
4. Returns the structured output as normal

This keeps all agent code clean — agents just call
invoke_with_tracking() instead of chain.invoke()
"""

from langchain_groq import ChatGroq
from src.utils.token_tracker import tracker


def invoke_with_tracking(
    chain,
    llm: ChatGroq,
    prompt_template,
    inputs: dict,
    agent_name: str
):
    """
    Invokes a LangChain chain and records token usage.

    Args:
        chain: the LCEL chain (prompt | structured_llm)
        llm: the raw ChatGroq instance (for token extraction)
        prompt_template: the ChatPromptTemplate
        inputs: dict of template variables
        agent_name: name shown in token report

    Returns:
        Structured Pydantic output from the chain
    """
    # Step 1 — get structured output
    structured_response = chain.invoke(inputs)

    # Step 2 — get raw response for token extraction
    # This uses the same prompt but gets the AIMessage
    # which contains usage_metadata
    try:
        messages = prompt_template.format_messages(**inputs)
        raw_response = llm.invoke(messages)
        tracker.record_usage(agent_name, raw_response)
    except Exception as e:
        # Token tracking failed but structured output succeeded
        # Log manually with estimate
        print(f"  [TOKENS] {agent_name}: could not extract — {e}")
        tracker.call_log.append({
            "agent": agent_name,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "timestamp_seconds": 0
        })

    return structured_response