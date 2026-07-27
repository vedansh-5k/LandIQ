"""
web_search.py
-------------
A web search tool for the Compliance and Research agents.

Uses Tavily API — a search engine specifically designed
and optimized for AI agents. Unlike Google which returns
HTML pages, Tavily returns clean, structured text that
AI agents can read directly.

Why Tavily instead of Google?
- Returns clean text, not HTML
- Summarizes results for AI consumption
- Specifically built for LLM agent use cases
- Free tier available

The Compliance agent uses this to search for:
- Current regulations and laws
- RERA requirements
- Industry-specific compliance rules
- Recent regulatory changes

This is important because the LLM's training data has
a cutoff date — regulations change. Web search gives
real-time regulatory information.
"""

import os
from langchain_community.tools.tavily_search import TavilySearchResults
from src.utils.config import TAVILY_API_KEY


def get_search_tool(max_results: int = 3) -> TavilySearchResults | None:
    """
    Returns a configured Tavily search tool.

    Returns None if TAVILY_API_KEY is not set,
    allowing the system to run without web search
    (graceful degradation).

    Args:
        max_results: Number of search results to return (default 3)

    Returns:
        TavilySearchResults tool or None
    """
    if not TAVILY_API_KEY:
        print(
            "WARNING: TAVILY_API_KEY not set. "
            "Web search tool disabled. "
            "Compliance agent will use LLM knowledge only."
        )
        return None

    # Set the API key in environment
    os.environ["TAVILY_API_KEY"] = TAVILY_API_KEY

    return TavilySearchResults(
        max_results=max_results,
        description=(
            "Search the web for current information including "
            "regulations, compliance requirements, market data, "
            "industry reports, and recent news. "
            "Use for any question requiring up-to-date information."
        )
    )


# Create a ready-to-use search tool instance
# This is imported directly by agents that need web search
search_tool = get_search_tool(max_results=3)