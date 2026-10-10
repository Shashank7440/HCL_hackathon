import os

def _bool(k, d="false"): return os.getenv(k, d).lower() in ("1", "true", "yes")

class Settings:
    OLLAMA_HOST   = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    LLM_PROVIDER  = os.getenv("LLM_PROVIDER", "ollama")   # ollama | openai_compat (disclosed fallback)
    MOCK_LLM      = _bool("MOCK_LLM")
    EMBED_MODEL   = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    CHROMA_PATH   = os.getenv("CHROMA_PATH", "data/chroma")
    DB_PATH       = os.getenv("DB_PATH", "data/app.db")
    TOP_K         = int(os.getenv("TOP_K", "6"))
    MIN_SCORE     = float(os.getenv("MIN_SCORE", "0.30"))
    CHUNK_TOKENS  = int(os.getenv("CHUNK_TOKENS", "400"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "60"))
    ADMIN_KEY     = os.getenv("ADMIN_KEY", "admin-demo-key")
    LLM_TIMEOUT_S = int(os.getenv("LLM_TIMEOUT_S", "60"))
    AUTO_EXTRACT_RULES = _bool("AUTO_EXTRACT_RULES")

settings = Settings()
