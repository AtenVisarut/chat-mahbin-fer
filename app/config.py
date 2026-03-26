import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================#
# ENVIRONMENT / SERVICES
# ============================================================================#
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Facebook Messenger
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "")
FB_APP_SECRET = os.getenv("FB_APP_SECRET", "")

# Admin Authentication
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "ladda")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ladda123")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")

# Cache configuration
CACHE_TTL = 3600  # 1 hour
PENDING_CONTEXT_TTL = 1800  # 30 minutes (เพิ่มจาก 5 นาที เพื่อให้ user มีเวลาตอบ)
MAX_CACHE_SIZE = 5000  # Maximum cache entries (เพิ่มจาก 1000 เป็น 5000)

# Rate limiting per user
USER_RATE_LIMIT = 20  # requests per minute
USER_RATE_WINDOW = 60  # seconds


# Redis configuration (for scale-out support)
# Set REDIS_URL or UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN
REDIS_URL = os.getenv("REDIS_URL")
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
USE_REDIS_CACHE = bool(REDIS_URL or UPSTASH_REDIS_REST_URL)

# Memory configuration
MAX_MEMORY_MESSAGES = 50  # Keep last 50 messages for context (ปรับจาก 100 เพื่อ performance)
MEMORY_CONTEXT_WINDOW = 10  # Use last 10 messages for context
MEMORY_CONTENT_PREVIEW = 800  # Characters to show in context preview (เพิ่มจาก 300 เพื่อให้ชื่อสินค้าไม่ถูกตัด)


# ============================================================================#
# AGENTIC RAG CONFIGURATION
# ============================================================================#
# Set to "1" to enable Agentic RAG pipeline for Q&A
# Set to "0" to disable (legacy functions have been removed)
USE_AGENTIC_RAG = os.getenv("USE_AGENTIC_RAG", "1") == "1"

# ============================================================================#
# LLM MODEL NAMES (centralized — change once, applies everywhere)
# ============================================================================#
LLM_MODEL_GENERAL_CHAT = os.getenv("LLM_MODEL_GENERAL_CHAT", "gpt-4o")
LLM_MODEL_INTENT = os.getenv("LLM_MODEL_INTENT", "gpt-4o")
LLM_MODEL_QUERY_UNDERSTANDING = os.getenv("LLM_MODEL_QUERY_UNDERSTANDING", "gpt-4o")
LLM_MODEL_RERANKING = os.getenv("LLM_MODEL_RERANKING", "gpt-4o")
LLM_MODEL_GROUNDING = os.getenv("LLM_MODEL_GROUNDING", "gpt-4o")
LLM_MODEL_RESPONSE_GEN = os.getenv("LLM_MODEL_RESPONSE_GEN", "gpt-4o")
LLM_MODEL_KNOWLEDGE = os.getenv("LLM_MODEL_KNOWLEDGE", "gpt-4o")
LLM_MODEL_ENTITY_EXTRACTION = os.getenv("LLM_MODEL_ENTITY_EXTRACTION", "gpt-4o")
LLM_MODEL_DEALER_EXTRACTION = os.getenv("LLM_MODEL_DEALER_EXTRACTION", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

AGENTIC_RAG_CONFIG = {
    # Vector search threshold (lowered to 0.25 for better recall)
    "VECTOR_THRESHOLD": float(os.getenv("AGENTIC_VECTOR_THRESHOLD", "0.25")),

    # Minimum rerank score to include in results
    "RERANK_THRESHOLD": float(os.getenv("AGENTIC_RERANK_THRESHOLD", "0.50")),

    # Minimum number of relevant documents to return
    "MIN_RELEVANT_DOCS": int(os.getenv("AGENTIC_MIN_DOCS", "3")),

    # Enable grounding check (hallucination prevention)
    "ENABLE_GROUNDING": os.getenv("AGENTIC_ENABLE_GROUNDING", "0") == "1",

    # Maximum citations to include in response
    "MAX_CITATIONS": int(os.getenv("AGENTIC_MAX_CITATIONS", "3")),
}
