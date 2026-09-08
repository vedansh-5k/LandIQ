"""
retriever.py
------------
RAG retrieval from ChromaDB.
TOON compresses retrieved context before sending to LLM.
Saves ~50% input tokens on real ChromaDB output.

Fallback strings below ("No context available.", "No relevant context found.")
are sentinels — src/agents/dynamic_agent.py checks for these exact strings
(NO_CONTEXT_SENTINELS) to swap in an honest "no data retrieved" instruction
instead of silently feeding them to the LLM as if they were real content.
Keep both lists in sync if these strings ever change.
"""

from pathlib import Path

from src.rag.vectorstore import get_or_create_vectorstore
from src.graph.state import LandQueryState
from src.utils.toon import compress_rag_context, log_compression


def build_land_query(state: LandQueryState) -> str:
    return (
        f"{state.get('area', '')} {state.get('city', '')} "
        f"{state.get('state', '')} "
        f"{state.get('land_type', '')} land plot price per "
        f"{state.get('land_unit', 'sq yard')}"
    )


def get_rag_context(query: str, k: int = 6) -> str:
    try:
        vectorstore = get_or_create_vectorstore()

        if vectorstore is None:
            return "No context available."

        docs = vectorstore.similarity_search(query, k=k)

        if not docs:
            return "No relevant context found."

        raw_chunks = []
        for doc in docs:
            text = doc.page_content.strip()
            if not text:
                continue
            source = (doc.metadata or {}).get("source", "")
            source_label = Path(source).name if source else "unknown report"
            raw_chunks.append("[Source: %s]\n%s" % (source_label, text))
        raw_context = "\n\n".join(raw_chunks)

        # TOON compression — saves ~50% on real ChromaDB output
        compressed = compress_rag_context(raw_context)
        log_compression("RAG context", raw_context, compressed)

        return compressed

    except Exception as e:
        print(f"RAG retrieval error: {e}")
        return "No context available."