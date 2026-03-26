"""
Redis Cache Layer - รองรับ Scale Out
ใช้ Upstash Redis (Serverless Redis) หรือ Redis ปกติ

ข้อดี:
- รองรับหลาย instances (scale horizontally)
- ไม่หายเมื่อ server restart
- Rate limiting ทำงานถูกต้องแม้มีหลาย instances

วิธีใช้:
1. สมัคร Upstash Redis (Free tier: 10,000 commands/day)
2. ตั้ง Environment Variables:
   - REDIS_URL=redis://default:xxx@xxx.upstash.io:6379
   หรือ
   - UPSTASH_REDIS_REST_URL=https://xxx.upstash.io
   - UPSTASH_REDIS_REST_TOKEN=xxx
"""
import os
import json
import logging
import time
from typing import Any, Optional, Tuple

# Load .env file if exists
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================================
# Redis Client Setup
# ============================================================================

redis_client = None
REDIS_URL = os.getenv("REDIS_URL")
UPSTASH_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

def init_redis():
    """Initialize Redis client"""
    global redis_client

    # Option 1: Upstash REST API (recommended for serverless)
    if UPSTASH_REST_URL and UPSTASH_REST_TOKEN:
        try:
            from upstash_redis import Redis
            redis_client = Redis(
                url=UPSTASH_REST_URL,
                token=UPSTASH_REST_TOKEN
            )
            # Test connection
            redis_client.ping()
            logger.info("✓ Redis initialized (Upstash REST API)")
            return True
        except ImportError:
            logger.warning("upstash-redis not installed, trying standard redis...")
        except Exception as e:
            logger.error(f"Upstash connection failed: {e}")

    # Option 2: Standard Redis URL
    if REDIS_URL:
        try:
            import redis
            redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            redis_client.ping()
            logger.info("✓ Redis initialized (Standard Redis)")
            return True
        except ImportError:
            logger.warning("redis package not installed")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")

    logger.warning("⚠️ Redis not configured - using in-memory cache fallback")
    return False

# Initialize on module load
_redis_initialized = init_redis()


def is_redis_available() -> bool:
    """Check if Redis is available"""
    return redis_client is not None


# ============================================================================
# Basic Cache Functions
# ============================================================================

def redis_get(key: str) -> Optional[Any]:
    """Get value from Redis"""
    if not redis_client:
        return None

    try:
        value = redis_client.get(key)
        if value:
            # Try to parse as JSON
            try:
                return json.loads(value) if isinstance(value, str) else value
            except json.JSONDecodeError:
                return value
        return None
    except Exception as e:
        logger.error(f"Redis GET error [{key}]: {e}")
        return None


def redis_set(key: str, value: Any, ttl: int = 3600) -> bool:
    """Set value to Redis with TTL (seconds)"""
    if not redis_client:
        return False

    try:
        # Serialize to JSON if not string
        if isinstance(value, (dict, list)):
            json_value = json.dumps(value, ensure_ascii=False, default=str)
        else:
            json_value = str(value)

        redis_client.set(key, json_value, ex=ttl)
        return True
    except Exception as e:
        logger.error(f"Redis SET error [{key}]: {e}")
        return False


def redis_delete(key: str) -> bool:
    """Delete key from Redis"""
    if not redis_client:
        return False

    try:
        redis_client.delete(key)
        return True
    except Exception as e:
        logger.error(f"Redis DELETE error [{key}]: {e}")
        return False


def redis_exists(key: str) -> bool:
    """Check if key exists in Redis"""
    if not redis_client:
        return False

    try:
        return bool(redis_client.exists(key))
    except Exception as e:
        logger.error(f"Redis EXISTS error [{key}]: {e}")
        return False


def redis_ttl(key: str) -> int:
    """Get TTL of key in seconds (-1 if no TTL, -2 if not exists)"""
    if not redis_client:
        return -2

    try:
        return redis_client.ttl(key)
    except Exception as e:
        logger.error(f"Redis TTL error [{key}]: {e}")
        return -2


# ============================================================================
# Rate Limiting Functions
# ============================================================================

def check_rate_limit_redis(
    user_id: str,
    limit: int = 10,
    window: int = 60
) -> Tuple[bool, int]:
    """
    Check rate limit using Redis INCR with TTL

    Args:
        user_id: User identifier
        limit: Maximum requests allowed in window
        window: Time window in seconds

    Returns:
        Tuple of (is_allowed, remaining_requests)
    """
    if not redis_client:
        # Fallback: allow all if Redis not available
        logger.debug("Redis not available, allowing request")
        return True, limit

    key = f"ratelimit:{user_id}"

    try:
        # Get current count
        current = redis_client.get(key)

        if current is None:
            # First request in window - set counter to 1 with TTL
            redis_client.set(key, 1, ex=window)
            logger.debug(f"Rate limit: {user_id[:8]}... first request ({limit-1} remaining)")
            return True, limit - 1

        count = int(current)

        if count >= limit:
            # Rate limit exceeded
            ttl = redis_client.ttl(key)
            logger.warning(
                f"⛔ Rate limit exceeded: {user_id[:8]}... "
                f"({count}/{limit}, resets in {ttl}s)"
            )
            return False, 0

        # Increment counter (atomic operation)
        new_count = redis_client.incr(key)
        remaining = max(0, limit - new_count)

        logger.debug(f"Rate limit: {user_id[:8]}... ({remaining} remaining)")
        return True, remaining

    except Exception as e:
        logger.error(f"Rate limit check error: {e}")
        # Allow on error to prevent blocking users
        return True, limit


def get_rate_limit_status_redis(user_id: str, limit: int = 10) -> dict:
    """Get current rate limit status for a user"""
    if not redis_client:
        return {
            "user_id": user_id[:8] + "...",
            "requests_used": 0,
            "limit": limit,
            "remaining": limit,
            "reset_in_seconds": 0,
            "redis_available": False
        }

    key = f"ratelimit:{user_id}"

    try:
        current = redis_client.get(key)
        ttl = redis_client.ttl(key)

        count = int(current) if current else 0

        return {
            "user_id": user_id[:8] + "...",
            "requests_used": count,
            "limit": limit,
            "remaining": max(0, limit - count),
            "reset_in_seconds": max(0, ttl),
            "redis_available": True
        }
    except Exception as e:
        logger.error(f"Get rate limit status error: {e}")
        return {
            "user_id": user_id[:8] + "...",
            "error": str(e),
            "redis_available": False
        }


# ============================================================================
# Image Analysis Cooldown
# ============================================================================

def check_image_cooldown_redis(
    user_id: str,
    cooldown: int = 10
) -> Tuple[bool, int]:
    """
    Check if user can send another image (cooldown between images)

    Args:
        user_id: User identifier
        cooldown: Cooldown period in seconds

    Returns:
        Tuple of (is_allowed, seconds_remaining)
    """
    if not redis_client:
        return True, 0

    key = f"img_cooldown:{user_id}"

    try:
        ttl = redis_client.ttl(key)

        if ttl > 0:
            # Still in cooldown period
            logger.info(f"Image cooldown: {user_id[:8]}... wait {ttl}s")
            return False, ttl

        # Set new cooldown
        redis_client.set(key, "1", ex=cooldown)
        return True, 0

    except Exception as e:
        logger.error(f"Image cooldown check error: {e}")
        return True, 0


# ============================================================================
# Concurrent Analysis Limiter (Semaphore)
# ============================================================================

def acquire_analysis_slot(max_concurrent: int = 10, timeout: int = 300) -> bool:
    """
    Try to acquire a slot for image analysis (distributed semaphore)

    Args:
        max_concurrent: Maximum concurrent analyses allowed
        timeout: Auto-release timeout in seconds (safety mechanism)

    Returns:
        True if slot acquired, False if at capacity
    """
    if not redis_client:
        return True

    key = "concurrent_analysis_count"

    try:
        # Atomic increment
        count = redis_client.incr(key)

        # Set TTL as safety mechanism (auto-release stuck slots)
        if count == 1:
            redis_client.expire(key, timeout)

        if count > max_concurrent:
            # At capacity - release the slot we just took
            redis_client.decr(key)
            logger.warning(f"Analysis queue full ({count-1}/{max_concurrent})")
            return False

        logger.debug(f"Analysis slot acquired ({count}/{max_concurrent})")
        return True

    except Exception as e:
        logger.error(f"Acquire analysis slot error: {e}")
        return True  # Allow on error


def release_analysis_slot():
    """Release analysis slot after completion"""
    if not redis_client:
        return

    key = "concurrent_analysis_count"

    try:
        count = redis_client.decr(key)
        # Ensure count doesn't go negative
        if count < 0:
            redis_client.set(key, 0)
        logger.debug(f"Analysis slot released (now: {max(0, count)})")
    except Exception as e:
        logger.error(f"Release analysis slot error: {e}")


def get_analysis_queue_status(max_concurrent: int = 10) -> dict:
    """Get current analysis queue status"""
    if not redis_client:
        return {"available": True, "redis_connected": False}

    key = "concurrent_analysis_count"

    try:
        count = redis_client.get(key)
        current = int(count) if count else 0

        return {
            "current": current,
            "max": max_concurrent,
            "available": current < max_concurrent,
            "redis_connected": True
        }
    except Exception as e:
        return {"error": str(e), "redis_connected": False}


# ============================================================================
# Cache Statistics
# ============================================================================

def get_redis_stats() -> dict:
    """Get Redis connection and usage statistics"""
    if not redis_client:
        return {
            "status": "not_connected",
            "message": "Redis not configured. Set REDIS_URL or UPSTASH_REDIS_REST_URL"
        }

    try:
        # Try to get info (may not be available on all Redis providers)
        if hasattr(redis_client, 'info'):
            info = redis_client.info()
            return {
                "status": "connected",
                "provider": "standard_redis",
                "used_memory": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", "unknown"),
                "total_commands": info.get("total_commands_processed", "unknown"),
                "uptime_days": info.get("uptime_in_days", "unknown")
            }
        else:
            # Upstash REST API doesn't have info()
            # Just verify connection works
            redis_client.ping()
            return {
                "status": "connected",
                "provider": "upstash_rest",
                "message": "Connection healthy"
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# ============================================================================
# Utility Functions
# ============================================================================

def clear_user_rate_limit(user_id: str) -> bool:
    """Clear rate limit for a specific user (admin function)"""
    return redis_delete(f"ratelimit:{user_id}")


def clear_user_cooldown(user_id: str) -> bool:
    """Clear image cooldown for a specific user (admin function)"""
    return redis_delete(f"img_cooldown:{user_id}")


def reset_analysis_counter() -> bool:
    """Reset concurrent analysis counter (admin function)"""
    return redis_delete("concurrent_analysis_count")
