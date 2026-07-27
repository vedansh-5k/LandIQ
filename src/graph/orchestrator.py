"""
orchestrator.py
---------------
LangGraph orchestrator for LandIQ.
Layer 1 parallel, Layer 2 parallel, Layer 3 + Senior sequential.
Langfuse direct tracing — no langchain dependency needed.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from langgraph.graph import StateGraph, END
from src.graph.state import LandQueryState
from src.rag.retriever import get_rag_context, build_land_query
from src.agents.location.agent import run_location_agent
from src.agents.legal.agent import run_legal_agent
from src.agents.financial.agent import run_financial_agent
from src.agents.market.agent import run_market_agent
from src.agents.bull.agent import run_bull_agent
from src.agents.bear.agent import run_bear_agent
from src.agents.due_diligence.agent import run_due_diligence_agent
from src.agents.senior_consultant.agent import run_senior_consultant
from src.utils.token_tracker import tracker

AGENT_GAP = 1.0


def run_rag_node(state: LandQueryState) -> dict:
    query = build_land_query(state)
    context = get_rag_context(query)
    print(f"RAG retrieved context for: {query[:60]}...")
    return {"rag_context": context}


def run_layer1_parallel(state: LandQueryState) -> dict:
    selected = state.get("selected_agents", ["all"])
    agents = [
        ("location",  run_location_agent),
        ("legal",     run_legal_agent),
        ("financial", run_financial_agent),
        ("market",    run_market_agent),
    ]
    results = {}

    def run_with_stagger(name, func, delay):
        time.sleep(delay)
        print(f"Running: {name}")
        return name, func(state)

    active = [
        (name, func) for name, func in agents
        if "all" in selected or name in selected
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_with_stagger, name, func, i * 0.5): name
            for i, (name, func) in enumerate(active)
        }
        for future in as_completed(futures):
            try:
                name, result = future.result()
                results.update(result)
            except Exception as e:
                agent_name = futures[future]
                print(f"Layer 1 agent {agent_name} failed: {e}")
                results["error_log"] = results.get("error_log", []) + [
                    f"{agent_name} failed: {str(e)}"
                ]
    return results


def run_layer2_parallel(state: LandQueryState) -> dict:
    selected = state.get("selected_agents", ["all"])
    results = {}

    def run_bull(delay):
        time.sleep(delay)
        print("Running: bull")
        return run_bull_agent(state)

    def run_bear(delay):
        time.sleep(delay)
        print("Running: bear")
        return run_bear_agent(state)

    tasks = []
    if "all" in selected or "bull" in selected:
        tasks.append(("bull", run_bull, 0.0))
    if "all" in selected or "bear" in selected:
        tasks.append(("bear", run_bear, 0.5))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(func, delay): name
            for name, func, delay in tasks
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                results.update(result)
            except Exception as e:
                agent_name = futures[future]
                print(f"Layer 2 agent {agent_name} failed: {e}")
                results["error_log"] = results.get("error_log", []) + [
                    f"{agent_name} failed: {str(e)}"
                ]
    return results


def run_layer3_node(state: LandQueryState) -> dict:
    selected = state.get("selected_agents", ["all"])
    if "all" in selected or "due_diligence" in selected:
        time.sleep(AGENT_GAP)
        print("Running: due_diligence")
        return run_due_diligence_agent(state)
    print("Skipped: due_diligence")
    return {"completed_agents": ["Due Diligence (Skipped)"]}


def run_senior_node(state: LandQueryState) -> dict:
    selected = state.get("selected_agents", ["all"])
    if "all" in selected or "senior_consultant" in selected:
        time.sleep(AGENT_GAP)
        print("Running: senior_consultant")
        return run_senior_consultant(state)
    print("Skipped: senior_consultant")
    return {"completed_agents": ["Senior Consultant (Skipped)"]}


def build_advisor_graph():
    graph = StateGraph(LandQueryState)
    graph.add_node("rag",               run_rag_node)
    graph.add_node("layer1",            run_layer1_parallel)
    graph.add_node("layer2",            run_layer2_parallel)
    graph.add_node("due_diligence",     run_layer3_node)
    graph.add_node("senior_consultant", run_senior_node)
    graph.set_entry_point("rag")
    graph.add_edge("rag",               "layer1")
    graph.add_edge("layer1",            "layer2")
    graph.add_edge("layer2",            "due_diligence")
    graph.add_edge("due_diligence",     "senior_consultant")
    graph.add_edge("senior_consultant", END)
    return graph.compile()


def _send_to_langfuse(initial_state, final_state, token_data):
    """
    Send trace to Langfuse using direct SDK — no LangChain needed.
    Works with langfuse 2.57+
    """
    import os
    try:
        from langfuse import Langfuse

        lf = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )

        # Create main trace
        trace = lf.trace(
            name="LandIQ-Analysis",
            user_id="landiq-user",
            metadata={
                "city": initial_state.get("city", ""),
                "area": initial_state.get("area", ""),
                "state": initial_state.get("state", ""),
                "land_type": initial_state.get("land_type", ""),
                "budget_inr": initial_state.get("total_budget", 0),
            },
            input={
                "location": f"{initial_state.get('area')}, {initial_state.get('city')}",
                "budget": initial_state.get("total_budget", 0),
                "purpose": initial_state.get("purpose", ""),
                "timeline": initial_state.get("timeline_years", 5),
            },
            output={
                "agents_completed": final_state.get("completed_agents", []),
                "total_tokens": token_data.get("total_tokens", 0),
                "input_tokens": token_data.get("input_tokens", 0),
                "output_tokens": token_data.get("output_tokens", 0),
                "cost_usd": token_data.get("estimated_cost_usd", 0),
                "duration_seconds": token_data.get("session_duration_seconds", 0),
            }
        )

        # Log each agent as a generation span
        for agent_log in token_data.get("per_agent_log", []):
            agent_name = agent_log.get("agent", "unknown")
            in_tok = agent_log.get("input_tokens", 0)
            out_tok = agent_log.get("output_tokens", 0)
            total_tok = agent_log.get("total_tokens", 0)

            trace.generation(
                name=agent_name,
                model="llama-3.3-70b-versatile",
                usage={
                    "input": in_tok,
                    "output": out_tok,
                    "total": total_tok,
                },
                input=f"Agent: {agent_name} | Input tokens: {in_tok}",
                output=f"Output tokens: {out_tok} | Total: {total_tok}",
            )

        lf.flush()
        print(f"  [LANGFUSE] Trace sent with {len(token_data.get('per_agent_log', []))} agents")
        print(f"  [LANGFUSE] View at: cloud.langfuse.com → Tracing")
        return True

    except ImportError:
        print("  [LANGFUSE] langfuse not installed")
        return False
    except Exception as e:
        print(f"  [LANGFUSE] Error: {e}")
        return False


def run_land_advisor(user_inputs: dict) -> LandQueryState:
    graph = build_advisor_graph()
    selected_agents = user_inputs.get("selected_agents", ["all"])

    initial_state: LandQueryState = {
        "state":                      user_inputs.get("state", ""),
        "city":                       user_inputs.get("city", ""),
        "area":                       user_inputs.get("area", ""),
        "pincode":                    user_inputs.get("pincode", ""),
        "land_size":                  float(user_inputs.get("land_size", 0)),
        "land_unit":                  user_inputs.get("land_unit", "sq_yards"),
        "land_type":                  user_inputs.get("land_type", "residential"),
        "has_title_deed":             user_inputs.get("has_title_deed", False),
        "total_budget":               float(user_inputs.get("total_budget", 0)),
        "construction_budget":        float(user_inputs.get("construction_budget", 0)),
        "taking_loan":                user_inputs.get("taking_loan", False),
        "loan_amount":                float(user_inputs.get("loan_amount", 0)),
        "loan_interest_rate":         float(user_inputs.get("loan_interest_rate", 0)),
        "purpose":                    user_inputs.get("purpose", ""),
        "timeline_years":             int(user_inputs.get("timeline_years", 5)),
        "monthly_income_expectation": float(user_inputs.get("monthly_income_expectation", 0)),
        "risk_tolerance":             user_inputs.get("risk_tolerance", "moderate"),
        "selected_agents":            selected_agents,
        "rag_context":                "",
        "location_output":            None,
        "legal_output":               None,
        "financial_output":           None,
        "market_output":              None,
        "bull_output":                None,
        "bear_output":                None,
        "due_diligence_output":       None,
        "final_recommendation":       None,
        "token_report":               {},
        "completed_agents":           [],
        "error_log":                  []
    }

    print("\n" + "="*55)
    print("LAND INVESTMENT ADVISOR — SESSION STARTED")
    print(f"Location : {initial_state['area']}, {initial_state['city']}")
    print(f"Budget   : INR {initial_state['total_budget']:,.0f}")
    print(f"Agents   : {selected_agents}")
    print("="*55 + "\n")

    tracker.reset()

    # Run the graph
    final_state = graph.invoke(initial_state)

    # Print token report
    tracker.print_report()
    final_state["token_report"] = tracker.get_summary()

    # Send to Langfuse after run completes
    _send_to_langfuse(initial_state, final_state, final_state["token_report"])

    print("\n" + "="*55)
    print("SESSION COMPLETE")
    print(f"Completed: {final_state.get('completed_agents', [])}")
    print("="*55 + "\n")

    return final_state