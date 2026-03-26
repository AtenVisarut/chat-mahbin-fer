import logging
from fastapi import APIRouter

from app.dependencies import openai_client, supabase_client
from app.services.cache import get_cache_stats, clear_all_caches

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def root():
    return {
        "status": "online",
        "service": "Plant Disease Detection Bot",
        "version": "2.0.0",
        "features": [
            "GPT-4o-mini Vision Analysis",
            "Vector Search Product Recommendation",
            "RAG Knowledge Base",
            "Context-Aware Chat",
            "Analytics Dashboard"
        ]
    }


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.7.0",
        "cache_stats": await get_cache_stats(),
        "services": {
            "openai": bool(openai_client),
            "supabase": bool(supabase_client)
        }
    }


@router.get("/cache/stats")
async def cache_stats_endpoint():
    return await get_cache_stats()
