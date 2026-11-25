"""
Rate limiting (tiêu chí 7) — Sliding window 60 giây lưu trong Redis.
"""
import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException
import redis

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent")

WINDOW_SECONDS = 60
_fallback_windows: dict[str, deque[float]] = defaultdict(deque)


def _rate_key(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"rate_limit:{digest}"


def _check_memory_fallback(redis_key: str, limit: int, now: float) -> None:
    window = _fallback_windows[redis_key]
    cutoff = now - WINDOW_SECONDS
    while window and window[0] <= cutoff:
        window.popleft()
    if len(window) >= limit:
        retry_after = max(1, int(window[0] + WINDOW_SECONDS - now) + 1)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please retry later.",
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)


def check_rate_limit(key: str) -> None:
    """Kiểm tra rate limit theo API key dùng Redis sorted set (sliding window 60s)."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = _rate_key(key)

    if r is None:
        _check_memory_fallback(redis_key, limit, now)
        return

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= limit:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            else:
                retry_after = WINDOW_SECONDS
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please retry later.",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError as exc:
        logger.warning("redis_rate_limit_fallback", extra={"error": str(exc)})
        _check_memory_fallback(redis_key, limit, now)
