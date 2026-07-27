import os
from dotenv import load_dotenv

load_dotenv()

# ── PRIMARY: Google Gemini (FREE — 1M tokens/day) ────────────
# Get free key at: aistudio.google.com → Get API Key
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# ── FALLBACK: Groq (if still has quota) ──────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# All numbered keys point to same key
GROQ_API_KEY_1 = GROQ_API_KEY
GROQ_API_KEY_2 = GROQ_API_KEY
GROQ_API_KEY_3 = GROQ_API_KEY
GROQ_API_KEY_4 = GROQ_API_KEY
GROQ_API_KEY_5 = GROQ_API_KEY
GROQ_API_KEY_6 = GROQ_API_KEY
GROQ_API_KEY_7 = GROQ_API_KEY
GROQ_API_KEY_8 = GROQ_API_KEY

# Model settings
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_MODEL_FAST = "llama-3.1-8b-instant"

# Google Gemini model — free tier
GEMINI_MODEL = "gemini-1.5-flash"

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
LANGCHAIN_PROJECT = os.getenv(
    "LANGCHAIN_PROJECT", "AI_Boardroom_V3")

CHROMA_DB_PATH = "./chroma_db"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
TOP_K_RESULTS = 4

TEMP_GROWTH = 0.7
TEMP_RISK = 0.3
TEMP_FINANCE = 0.1
TEMP_COMPLIANCE = 0.2
TEMP_ADVOCATE = 0.8
TEMP_DEVIL = 0.9
TEMP_ARBITER = 0.3
TEMP_FACTCHECK = 0.1
TEMP_SENIOR = 0.4

# Check which key is available
if not GROQ_API_KEY and not GOOGLE_API_KEY:
    print("WARNING: No API key found. Add GROQ_API_KEY or GOOGLE_API_KEY to .env")