"""All runtime configuration comes from environment variables (Vercel project settings in production,
backend/.env locally). See .env.example for the full list."""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


# --- LLM (Groq) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")          # grounded policy answers
# small, fast model that only rewords replies whose facts were decided in code ("" turns rewording off)
# openai/gpt-oss-20b: $0.075 / $0.30 per 1M input / output tokens on Groq (console.groq.com/docs/models, Nov 2026);
# llama-3.1-8b-instant is listed as Enterprise-only there.
PHRASE_MODEL = os.getenv("PHRASE_MODEL", "openai/gpt-oss-20b").strip()
PHRASE_MAX_TOKENS = int(os.getenv("PHRASE_MAX_TOKENS", "300"))   # reasoning tokens count too (effort "low")
PHRASE_TIMEOUT_S = float(os.getenv("PHRASE_TIMEOUT_S", "4"))

# --- Database ---
# Set MONGO_URI in the Vercel project settings (or backend/.env locally). Never commit a connection string.
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "hr_chatbot_db")

# --- HTTP ---
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
MAX_UPLOAD_MB = _float("MAX_UPLOAD_MB", 5)

# --- Embeddings: "hf" | "gemini" | "none" (lexical BM25 only) ---
EMBEDDINGS_PROVIDER = os.getenv("EMBEDDINGS_PROVIDER", "none").strip().lower()
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_EMBED_MODEL = os.getenv("HF_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
HF_EMBED_URL = os.getenv(
    "HF_EMBED_URL",
    "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction",
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_EMBED_DIM = _int("GEMINI_EMBED_DIM", 768)
EMBED_BATCH = _int("EMBED_BATCH", 32)
EMBED_TIMEOUT_S = _float("EMBED_TIMEOUT_S", 20)

# --- Retrieval ---
RAG_TOP_K = _int("RAG_TOP_K", 5)
RAG_MIN_SCORE = _float("RAG_MIN_SCORE", 0.2)
RAG_HYBRID_ALPHA = _float("RAG_HYBRID_ALPHA", 0.6)   # weight of the vector score; 1 - alpha goes to BM25
RAG_RELATIVE_CUTOFF = _float("RAG_RELATIVE_CUTOFF", 0.4)  # drop hits scoring under this share of the best hit
RAG_CHUNK_CHARS = _int("RAG_CHUNK_CHARS", 800)
RAG_CHUNK_OVERLAP = _int("RAG_CHUNK_OVERLAP", 120)
ATLAS_VECTOR_INDEX = os.getenv("ATLAS_VECTOR_INDEX", "").strip()   # set to use Atlas $vectorSearch

# --- Demo data ---
AUTO_SEED = os.getenv("AUTO_SEED", "true").lower() != "false"
