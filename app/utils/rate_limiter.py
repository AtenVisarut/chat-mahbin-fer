"""
Rate Limiter - รองรับทั้ง Redis และ In-Memory Cache

Priority:
1. Redis (ถ้ามี) - รองรับ scale-out, หลาย instances
2. In-Memory Cache (fallback) - single instance only

การใช้งาน:
- check_user_rate_limit(user_id) - ตรวจสอบ rate limit
- check_image_cooldown(user_id) - ตรวจสอบ cooldown ระหว่างส่งรูป
- get_rate_limit_status(user_id) - ดูสถานะ rate limit
"""
import time
import logging
from typing import Tuple

from app.config import (
    USER_RATE_LIMIT,
    USER_RATE_WINDOW,
    USE_REDIS_CACHE
)

# Legacy image analysis constants (disease detection removed)
IMAGE_COOLDOWN = 10
MAX_CONCURRENT_ANALYSIS = 10

logger = logging.getLogger(__name__)

# ============================================================================
# Initialize Cache Backend
# ============================================================================

_use_redis = False
_redis_module = None

if USE_REDIS_CACHE:
    try:
        from app.services import redis_cache as _redis_module
        _use_redis = _redis_module.is_redis_available()
        if _use_redis:
            logger.info("✓ Rate limiter using Redis backend")
        else:
            logger.warning("⚠️ Redis configured but not available, using memory cache")
    except ImportError as e:
        logger.warning(f"⚠️ Redis module import failed: {e}")
        _use_redis = False

if not _use_redis:
    logger.info("Rate limiter using In-Memory cache (single instance only)")

# Import memory cache as fallback
from app.services.cache import get_from_memory_cache, set_to_memory_cache


# ============================================================================
# Rate Limit Functions
# ============================================================================

async def check_user_rate_limit(user_id: str) -> bool:
    """
    Check if user exceeded rate limit

    Uses Redis if available, otherwise falls back to In-Memory Cache

    Returns:
        True if request is allowed, False if rate limited
    """
    if _use_redis and _redis_module:
        # Use Redis (supports scale-out)
        is_allowed, remaining = _redis_module.check_rate_limit_redis(
            user_id,
            limit=USER_RATE_LIMIT,
            window=USER_RATE_WINDOW
        )
        return is_allowed

    # Fallback: In-Memory Cache (single instance only)
    return await _check_rate_limit_memory(user_id)


async def _check_rate_limit_memory(user_id: str) -> bool:
    """Rate limit check using In-Memory Cache (fallback)"""
    current_time = time.time()
    cache_key = f"ratelimit:{user_id}"

    # Get current timestamps from L1 memory cache
    timestamps = get_from_memory_cache(cache_key)

    if not timestamps:
        timestamps = []

    # Remove old timestamps outside the window
    valid_timestamps = [
        ts for ts in timestamps
        if current_time - ts < USER_RATE_WINDOW
    ]

    # Check if exceeded limit
    if len(valid_timestamps) >= USER_RATE_LIMIT:
        logger.warning(
            f"⛔ Rate limit exceeded: {user_id[:8]}... "
            f"({len(valid_timestamps)}/{USER_RATE_LIMIT})"
        )
        return False

    # Add current request
    valid_timestamps.append(current_time)

    # Save back to memory cache with TTL
    set_to_memory_cache(cache_key, valid_timestamps, ttl=USER_RATE_WINDOW)

    return True


# ============================================================================
# Image Cooldown Functions
# ============================================================================

async def check_image_cooldown(user_id: str, cooldown: int = None) -> Tuple[bool, int]:
    """
    Check if user can send another image (cooldown between images)

    Args:
        user_id: User identifier
        cooldown: Override cooldown seconds (default from config)

    Returns:
        Tuple of (is_allowed, seconds_remaining)
    """
    if cooldown is None:
        cooldown = IMAGE_COOLDOWN

    if _use_redis and _redis_module:
        return _redis_module.check_image_cooldown_redis(user_id, cooldown)

    # Fallback: In-Memory Cache
    return await _check_image_cooldown_memory(user_id, cooldown)


async def _check_image_cooldown_memory(user_id: str, cooldown: int) -> Tuple[bool, int]:
    """Image cooldown check using In-Memory Cache (fallback)"""
    cache_key = f"img_cooldown:{user_id}"
    last_time = get_from_memory_cache(cache_key)

    if last_time:
        elapsed = time.time() - last_time
        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            logger.info(f"Image cooldown: {user_id[:8]}... wait {remaining}s")
            return False, remaining

    # Set new cooldown
    set_to_memory_cache(cache_key, time.time(), ttl=cooldown)
    return True, 0


# ============================================================================
# Concurrent Analysis Limiter
# ============================================================================

async def acquire_analysis_slot() -> bool:
    """
    Try to acquire a slot for image analysis

    Limits concurrent image analyses to prevent overload

    Returns:
        True if slot acquired, False if at capacity
    """
    if _use_redis and _redis_module:
        return _redis_module.acquire_analysis_slot(MAX_CONCURRENT_ANALYSIS)

    # Fallback: No limit for single instance (memory-based counting is unreliable)
    return True


async def release_analysis_slot():
    """Release analysis slot after completion"""
    if _use_redis and _redis_module:
        _redis_module.release_analysis_slot()


# ============================================================================
# Status Functions
# ============================================================================

def get_rate_limit_status(user_id: str) -> dict:
    """Get current rate limit status for a user"""
    if _use_redis and _redis_module:
        status = _redis_module.get_rate_limit_status_redis(user_id, USER_RATE_LIMIT)
        status["backend"] = "redis"
        return status

    # Fallback: In-Memory Cache
    return _get_rate_limit_status_memory(user_id)


def _get_rate_limit_status_memory(user_id: str) -> dict:
    """Get rate limit status from In-Memory Cache"""
    current_time = time.time()
    cache_key = f"ratelimit:{user_id}"

    timestamps = get_from_memory_cache(cache_key)

    if not timestamps:
        return {
            "user_id": user_id[:8] + "...",
            "requests_in_window": 0,
            "limit": USER_RATE_LIMIT,
            "window_seconds": USER_RATE_WINDOW,
            "remaining": USER_RATE_LIMIT,
            "backend": "memory"
        }

    valid_timestamps = [
        ts for ts in timestamps
        if current_time - ts < USER_RATE_WINDOW
    ]

    return {
        "user_id": user_id[:8] + "...",
        "requests_in_window": len(valid_timestamps),
        "limit": USER_RATE_LIMIT,
        "window_seconds": USER_RATE_WINDOW,
        "remaining": max(0, USER_RATE_LIMIT - len(valid_timestamps)),
        "backend": "memory"
    }


def get_analysis_queue_status() -> dict:
    """Get current analysis queue status"""
    if _use_redis and _redis_module:
        return _redis_module.get_analysis_queue_status(MAX_CONCURRENT_ANALYSIS)

    return {
        "message": "Queue status not available (memory cache mode)",
        "backend": "memory"
    }


# ============================================================================
# Cleanup Functions
# ============================================================================

async def cleanup_rate_limit_data():
    """
    Clean up old rate limit data.

    With TTL-based caching (both Redis and Memory), this is handled automatically.
    Kept for compatibility with existing imports.
    """
    pass


# ============================================================================
# Admin Functions
# ============================================================================

def clear_user_rate_limit(user_id: str) -> bool:
    """Clear rate limit for a specific user (admin function)"""
    if _use_redis and _redis_module:
        return _redis_module.clear_user_rate_limit(user_id)

    # Memory cache doesn't support targeted deletion easily
    return False


def clear_user_cooldown(user_id: str) -> bool:
    """Clear image cooldown for a specific user (admin function)"""
    if _use_redis and _redis_module:
        return _redis_module.clear_user_cooldown(user_id)

    return False


def get_cache_backend_info() -> dict:
    """Get information about the current cache backend"""
    if _use_redis and _redis_module:
        stats = _redis_module.get_redis_stats()
        stats["backend"] = "redis"
        return stats

    return {
        "backend": "memory",
        "status": "active",
        "warning": "In-memory cache does not support scale-out"
    }
