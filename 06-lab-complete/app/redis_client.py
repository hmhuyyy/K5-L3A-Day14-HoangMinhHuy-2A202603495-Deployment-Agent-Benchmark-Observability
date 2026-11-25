"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

App vẫn khởi động được khi Redis chưa sẵn sàng (không ping lúc import).
"""
from typing import Optional

import redis

from app.config import settings


def _create_client() -> Optional[redis.Redis]:
    if not settings.redis_url:
        return None
    try:
        return redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
    except Exception:
        return None


r: Optional[redis.Redis] = _create_client()


def redis_healthy() -> bool:
    """Ping Redis cho GET /ready; lỗi kết nối → False."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except Exception:
        return False


def close_redis() -> None:
    """Đóng connection pool khi shutdown."""
    if r is not None:
        try:
            r.close()
        except Exception:
            pass
