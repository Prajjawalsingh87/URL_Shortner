"""
cache.py - Redis cache integration for URL lookups.
Caches short_code -> original_url mappings for fast redirects.
All Redis credentials are loaded from environment variables.
"""

import os
import logging
import redis.asyncio as aioredis
from typing import Optional

logger = logging.getLogger(__name__)

# Redis connection URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Default TTL for cached entries (1 hour)
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

# Global async Redis client (initialized on startup)
redis_client: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    """Initialize async Redis connection pool on app startup."""
    global redis_client
    try:
        redis_client = aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=3,
        )
        # Verify connection
        await redis_client.ping()
        logger.info("✅ Redis connected successfully")
    except Exception as e:
        logger.warning(f"⚠️  Redis connection failed: {e}. Cache will be disabled.")
        redis_client = None


async def close_redis() -> None:
    """Close Redis connection on app shutdown."""
    global redis_client
    if redis_client:
        await redis_client.aclose()
        redis_client = None
        logger.info("Redis connection closed.")


async def get_cached_url(short_code: str) -> Optional[str]:
    """
    Retrieve original URL from Redis cache by short_code.
    Returns None if not cached or Redis is unavailable.
    """
    if not redis_client:
        return None
    try:
        cached = await redis_client.get(f"url:{short_code}")
        return cached
    except Exception as e:
        logger.warning(f"Redis GET error for {short_code}: {e}")
        return None


async def set_cached_url(short_code: str, original_url: str, ttl: int = CACHE_TTL) -> None:
    """
    Store short_code -> original_url in Redis with TTL.
    Silently fails if Redis is unavailable.
    """
    if not redis_client:
        return
    try:
        await redis_client.setex(f"url:{short_code}", ttl, original_url)
    except Exception as e:
        logger.warning(f"Redis SET error for {short_code}: {e}")


async def delete_cached_url(short_code: str) -> None:
    """Remove a short_code entry from cache (on deletion or deactivation)."""
    if not redis_client:
        return
    try:
        await redis_client.delete(f"url:{short_code}")
    except Exception as e:
        logger.warning(f"Redis DELETE error for {short_code}: {e}")


async def is_redis_healthy() -> bool:
    """Check if Redis connection is alive. Used in health check endpoint."""
    if not redis_client:
        return False
    try:
        return await redis_client.ping()
    except Exception:
        return False
