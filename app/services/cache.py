import time
import hashlib
import logging
import json
import base64
import threading
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from app.config import CACHE_TTL, PENDING_CONTEXT_TTL, MAX_CACHE_SIZE
from app.dependencies import supabase_client

logger = logging.getLogger(__name__)

# ============================================================================
# In-Memory Cache Layer (L1 Cache)
# ============================================================================
# ใช้ dict เก็บ cache ใน memory เพื่อลด Supabase queries
# - L1: In-Memory (เร็วมาก ~0.1ms)
# - L2: Supabase (fallback ~50-200ms)

class InMemoryCache:
    """Thread-safe in-memory cache with TTL support.

    Uses threading.Lock (not asyncio.Lock) intentionally:
    all operations inside the lock are fast CPU-bound dict access
    with no I/O or await, so blocking is negligible (<1ms).
    This also allows synchronous callers (e.g. rate-limiting) to use it.
    """

    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Get item from memory cache"""
        with self._lock:
            if key in self._cache:
                item = self._cache[key]
                # Check if expired
                if item["expires_at"] > time.time():
                    self._hits += 1
                    return item["value"]
                else:
                    # Expired - remove it
                    del self._cache[key]
            self._misses += 1
            return None
    
    def set(self, key: str, value: Any, ttl: int):
        """Set item to memory cache"""
        with self._lock:
            # Evict oldest items if cache is full
            if len(self._cache) >= self._max_size:
                self._evict_oldest()
            
            self._cache[key] = {
                "value": value,
                "expires_at": time.time() + ttl,
                "created_at": time.time()
            }
    
    def delete(self, key: str):
        """Delete item from memory cache"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def clear(self):
        """Clear all items from memory cache"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def _evict_oldest(self):
        """Remove oldest 10% of items when cache is full"""
        if not self._cache:
            return
        
        # Sort by created_at and remove oldest 10%
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k]["created_at"]
        )
        evict_count = max(1, len(sorted_keys) // 10)
        
        for key in sorted_keys[:evict_count]:
            del self._cache[key]
        
        logger.info(f"Memory cache evicted {evict_count} oldest items")
    
    def cleanup_expired(self):
        """Remove all expired items"""
        with self._lock:
            current_time = time.time()
            expired_keys = [
                k for k, v in self._cache.items()
                if v["expires_at"] <= current_time
            ]
            for key in expired_keys:
                del self._cache[key]
            
            if expired_keys:
                logger.info(f"Memory cache cleaned up {len(expired_keys)} expired items")
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                "items": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_percent": round(hit_rate, 2)
            }


# Global in-memory cache instance
_memory_cache = InMemoryCache(max_size=MAX_CACHE_SIZE)


# ============================================================================
# Helper Functions
# ============================================================================

def get_image_hash(image_bytes: bytes) -> str:
    """Generate hash for image caching"""
    return hashlib.md5(image_bytes).hexdigest()


def get_cache_key(prefix: str, key: str) -> str:
    """Generate cache key with prefix"""
    return f"{prefix}:{key}"


# ============================================================================
# Two-Layer Cache Functions (L1: Memory, L2: Supabase)
# ============================================================================

async def get_from_cache(cache_type: str, key: str) -> Optional[Any]:
    """
    Get item from cache (L1 Memory → L2 Supabase)
    
    Flow:
    1. Check L1 (Memory) - ~0.1ms
    2. If miss, check L2 (Supabase) - ~50-200ms
    3. If found in L2, populate L1
    """
    full_key = f"{cache_type}:{key}"
    
    # L1: Check memory cache first (fast!)
    value = _memory_cache.get(full_key)
    if value is not None:
        logger.debug(f"✓ L1 Cache hit: {full_key[:50]}")
        return value
    
    # L2: Fallback to Supabase
    try:
        if not supabase_client:
            return None
        
        result = supabase_client.table('cache')\
            .select('value, expires_at')\
            .eq('key', full_key)\
            .gt('expires_at', datetime.now(timezone.utc).isoformat())\
            .execute()
        
        if result.data:
            value = result.data[0]['value']
            
            # Calculate remaining TTL
            expires_at_str = result.data[0]['expires_at']
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            remaining_ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
            
            # Populate L1 cache with remaining TTL
            if remaining_ttl > 0:
                _memory_cache.set(full_key, value, remaining_ttl)
            
            logger.info(f"✓ L2 Cache hit (populated L1): {full_key[:50]}")
            return value
        
        return None
        
    except Exception as e:
        logger.error(f"Cache get error: {e}")
        return None


async def set_to_cache(cache_type: str, key: str, data: Any, ttl: int = CACHE_TTL):
    """
    Set item to cache (L1 Memory + L2 Supabase)
    
    Flow:
    1. Set to L1 (Memory) - immediate
    2. Set to L2 (Supabase) - async persistence
    """
    full_key = f"{cache_type}:{key}"
    
    # L1: Set to memory cache (fast!)
    _memory_cache.set(full_key, data, ttl)
    
    # L2: Persist to Supabase
    try:
        if not supabase_client:
            return
        
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        
        supabase_client.table('cache').upsert({
            'key': full_key,
            'value': data,
            'expires_at': expires_at
        }).execute()
        
        logger.debug(f"✓ Cache set (L1+L2): {full_key[:50]}")
        
    except Exception as e:
        logger.error(f"Cache set error (L2): {e}")
        # L1 is still set, so cache works even if Supabase fails


async def delete_from_cache(cache_type: str, key: str):
    """Delete item from both L1 and L2 cache"""
    full_key = f"{cache_type}:{key}"
    
    # L1: Delete from memory
    _memory_cache.delete(full_key)
    
    # L2: Delete from Supabase
    try:
        if supabase_client:
            supabase_client.table('cache').delete().eq('key', full_key).execute()
    except Exception as e:
        logger.error(f"Cache delete error: {e}")


# ============================================================================
# Pending Context Helpers (Special handling for image bytes)
# ============================================================================

async def save_pending_context(user_id: str, context_data: Dict[str, Any]):
    """Save pending context to cache (handles bytes serialization)"""
    try:
        # Create a copy to modify
        data_to_save = context_data.copy()
        
        # Convert bytes to base64 string for JSON storage
        if "image_bytes" in data_to_save and isinstance(data_to_save["image_bytes"], bytes):
            data_to_save["image_bytes"] = base64.b64encode(data_to_save["image_bytes"]).decode('utf-8')
            data_to_save["_is_bytes"] = True
        
        await set_to_cache("context", user_id, data_to_save, ttl=PENDING_CONTEXT_TTL)
        
    except Exception as e:
        logger.error(f"Error saving pending context: {e}")


async def get_pending_context(user_id: str) -> Optional[Dict[str, Any]]:
    """Get pending context from cache (handles bytes deserialization)"""
    try:
        data = await get_from_cache("context", user_id)
        if not data:
            return None
        
        # Convert base64 string back to bytes
        if data.get("_is_bytes") and "image_bytes" in data:
            data["image_bytes"] = base64.b64decode(data["image_bytes"])
        
        return data
        
    except Exception as e:
        logger.error(f"Error getting pending context: {e}")
        return None


async def delete_pending_context(user_id: str):
    """Delete pending context from cache"""
    await delete_from_cache("context", user_id)


# ============================================================================
# Cleanup & Stats
# ============================================================================

async def cleanup_expired_cache():
    """Clean up expired cache entries in both L1 and L2"""
    # L1: Clean memory cache
    _memory_cache.cleanup_expired()
    
    # L2: Clean Supabase cache
    try:
        if not supabase_client:
            return
        
        result = supabase_client.table('cache')\
            .delete()\
            .lt('expires_at', datetime.now(timezone.utc).isoformat())\
            .execute()
        
        if result.data:
            logger.info(f"L2 Cache cleanup: removed {len(result.data)} expired entries")
            
    except Exception as e:
        logger.error(f"Cache cleanup error: {e}")


async def clear_all_caches():
    """Clear all cache entries in both L1 and L2"""
    # L1: Clear memory cache
    _memory_cache.clear()
    logger.info("L1 Memory cache cleared")
    
    # L2: Clear Supabase cache
    try:
        if supabase_client:
            supabase_client.table('cache').delete().neq('key', '0').execute()
            logger.info("L2 Supabase cache cleared")
    except Exception as e:
        logger.error(f"Error clearing L2 cache: {e}")


async def get_cache_stats() -> dict:
    """Get cache statistics from both L1 and L2"""
    stats = {
        "l1_memory": _memory_cache.get_stats(),
        "l2_supabase": {"status": "unknown"}
    }
    
    try:
        if supabase_client:
            result = supabase_client.table('cache').select('key', count='exact').execute()
            stats["l2_supabase"] = {
                "items": result.count if result.count is not None else 0,
                "storage": "Supabase (PostgreSQL)"
            }
    except Exception as e:
        stats["l2_supabase"] = {"error": str(e)}
    
    return stats


# ============================================================================
# Memory Cache Direct Access (for rate limiting - needs to be fast)
# ============================================================================

def get_from_memory_cache(key: str) -> Optional[Any]:
    """Direct access to L1 memory cache (synchronous, for rate limiting)"""
    return _memory_cache.get(key)


def set_to_memory_cache(key: str, value: Any, ttl: int):
    """Direct set to L1 memory cache (synchronous, for rate limiting)"""
    _memory_cache.set(key, value, ttl)


def delete_from_memory_cache(key: str):
    """Direct delete from L1 memory cache (synchronous)"""
    _memory_cache.delete(key)
