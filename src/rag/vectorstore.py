"""
vectorstore.py
--------------
Converts document chunks into embeddings and stores in ChromaDB.

Flow:
1. Take chunks from loader.py
2. Convert each chunk to 384-dimensional number vector
   using SentenceTransformer (runs locally, free)
3. Store vectors + original text in ChromaDB on your laptop
4. Later: search ChromaDB with a query to find similar chunks

Why SentenceTransformer all-MiniLM-L6-v2?
- Runs completely locally — no API key needed
- Fast — small model, quick inference
- Good quality — captures semantic meaning well
- Free — no cost per embedding
- 384 dimensions — good balance of quality vs speed

ChromaDB:
- Saves to ./chroma_db folder on your laptop
- Persists between sessions — no need to rebuild every run
- Fast similarity search using cosine distance
"""

import os
import threading
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
from src.utils.config import CHROMA_DB_PATH, EMBEDDING_MODEL

_LOAD_LOCK = threading.Lock()


def get_embeddings() -> SentenceTransformerEmbeddings:
    """
    Returns the SentenceTransformer embedding model.

    This model:
    - Downloads once on first run (~80MB)
    - Runs locally after that — no internet needed
    - Converts text to 384-dimensional vectors
    - Completely free, no API key required
    """
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    return SentenceTransformerEmbeddings(
        model_name=EMBEDDING_MODEL
    )


def create_vectorstore(chunks: list) -> Chroma:
    """
    Creates a new ChromaDB vector store from chunks.

    Process:
    1. Takes each chunk's text
    2. Converts to 384-number vector using embeddings model
    3. Stores (vector + original text + metadata) in ChromaDB
    4. Saves to disk at CHROMA_DB_PATH

    This only needs to run once — or when you add new PDFs.
    """
    if not chunks:
        print("No chunks to embed — vectorstore not created")
        return None

    print(f"Creating vectorstore from {len(chunks)} chunks...")
    embeddings = get_embeddings()

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DB_PATH
    )

    print(f"Vectorstore created and saved to {CHROMA_DB_PATH}")
    print(f"Total vectors stored: {len(chunks)}")

    global _LOADED_VECTORSTORE
    _LOADED_VECTORSTORE = vectorstore
    return vectorstore


_LOADED_VECTORSTORE = None  # process-wide singleton, see load_vectorstore()


def load_vectorstore() -> Chroma | None:
    """
    Loads existing ChromaDB from disk.

    Returns None if no vectorstore exists yet.
    This avoids rebuilding every time the app starts.

    Cached at module level after the first successful load: every one of the
    10+ agents on the Langflow path calls get_rag_context() -> here on its
    own HTTP request, and reloading the SentenceTransformer model plus
    reopening the persisted Chroma DB from scratch on every single call was
    real, avoidable overhead stacking on top of every agent's LLM call -
    contributing to agents timing out under load. The underlying files never
    change during a run, so loading once per process and reusing it is safe.

    The orchestrator now dispatches 2 agents concurrently per layer (see
    LandIQOrchestrator's ThreadPoolExecutor), so two threads could both see
    the cache empty and race to open the same on-disk Chroma DB at once -
    observed as "Could not connect to tenant default_tenant" under load.
    _LOAD_LOCK makes that double-checked-locking safe: only one thread ever
    actually opens the DB, the other just waits and reuses the result.
    """
    global _LOADED_VECTORSTORE
    if _LOADED_VECTORSTORE is not None:
        return _LOADED_VECTORSTORE

    with _LOAD_LOCK:
        if _LOADED_VECTORSTORE is not None:
            return _LOADED_VECTORSTORE

        if not os.path.exists(CHROMA_DB_PATH):
            print("No existing vectorstore found")
            return None

        embeddings = get_embeddings()

        vectorstore = Chroma(
            persist_directory=CHROMA_DB_PATH,
            embedding_function=embeddings
        )

        print(f"Loaded existing vectorstore from {CHROMA_DB_PATH}")
        _LOADED_VECTORSTORE = vectorstore
        return vectorstore


def get_or_create_vectorstore(chunks: list = None) -> Chroma | None:
    """
    Main function called by retriever.py

    Logic:
    1. Try to load existing vectorstore from disk
    2. If exists AND no new chunks → return existing
    3. If new chunks provided → create fresh vectorstore
    4. If nothing exists and no chunks → return None

    This means:
    - First run: creates vectorstore from PDFs
    - Subsequent runs: loads from disk (fast)
    - When new PDFs added: pass chunks to rebuild
    """
    existing = load_vectorstore()

    # No new chunks provided — use existing if available
    if chunks is None:
        if existing:
            return existing
        else:
            print("No vectorstore and no chunks — RAG disabled")
            return None

    # New chunks provided — always rebuild fresh
    print("Building fresh vectorstore from new chunks...")
    return create_vectorstore(chunks)