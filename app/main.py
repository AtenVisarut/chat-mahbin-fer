# พี่ม้าบิน Fertilizer Chatbot v2.5.1
import logging
import asyncio
import os
import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager

from app.config import (
    LINE_CHANNEL_ACCESS_TOKEN,
    FB_PAGE_ACCESS_TOKEN,
    OPENAI_API_KEY,
    SECRET_KEY,
)
from app.dependencies import openai_client, supabase_client, analytics_tracker
from app.services.cache import cleanup_expired_cache, clear_all_caches
from app.services.product.registry import ProductRegistry
from app.utils.rate_limiter import cleanup_rate_limit_data

# Routers
from app.routers import health, admin, dashboard, webhook, facebook_webhook

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================#
# Lifespan Events
# ============================================================================#

async def periodic_cleanup():
    """Periodic cleanup task"""
    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            logger.info("Running periodic cleanup...")
            await cleanup_expired_cache()
            await cleanup_rate_limit_data()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")
            await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # Startup
    logger.info("=" * 60)
    logger.info("Starting พี่ม้าบิน Fertilizer Chatbot")
    logger.info(f"OpenAI API: {'✓' if OPENAI_API_KEY else '✗'}")
    logger.info(f"Supabase: {'✓' if supabase_client else '✗'}")
    logger.info(f"LINE Bot: {'✓' if LINE_CHANNEL_ACCESS_TOKEN else '✗'}")
    logger.info(f"Facebook: {'✓' if FB_PAGE_ACCESS_TOKEN else '✗'}")
    logger.info(f"Analytics: {'✓' if analytics_tracker else '✗'}")
    logger.info("=" * 60)

    # Load product registry from DB
    registry = ProductRegistry.get_instance()
    await registry.load_from_db(supabase_client)
    logger.info(f"ProductRegistry: {'✓' if registry.loaded else '✗'} ({len(registry.get_canonical_list())} products)")

    # Start background tasks only when explicitly enabled (not recommended on serverless)
    RUN_BACKGROUND_TASKS = os.getenv("RUN_BACKGROUND_TASKS", "0") == "1"
    cleanup_task = None
    if RUN_BACKGROUND_TASKS:
        logger.info("Starting background tasks...")
        cleanup_task = asyncio.create_task(periodic_cleanup())
    else:
        logger.info("RUN_BACKGROUND_TASKS not set or false — skipping background tasks (serverless mode)")

    yield

    # Shutdown
    logger.info("Shutting down gracefully...")
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

    # Clear all caches
    await clear_all_caches()
    logger.info("All caches cleared")


# Initialize FastAPI app
app = FastAPI(
    title="พี่ม้าบิน Fertilizer Chatbot",
    description="AI-powered fertilizer recommendation chatbot with Agentic RAG",
    version="2.0.0",
    lifespan=lifespan
)

# Initialize Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add Session Middleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(health.router)
app.include_router(admin.router)
app.include_router(dashboard.router)
app.include_router(webhook.router)
app.include_router(facebook_webhook.router)


if __name__ == "__main__":
    # อ่าน Port จาก Environment Variable ที่ Cloud Platform (Fly.io/Vercel) ส่งมา
    # และใช้ 8080 เป็นค่า Default (ตามที่ Fly.io แนะนำ)
    port = int(os.environ.get("PORT", 8080))

    # รัน Uvicorn ด้วยค่า Port ที่อ่านได้
    uvicorn.run('app.main:app', host='0.0.0.0', port=port, reload=True)
