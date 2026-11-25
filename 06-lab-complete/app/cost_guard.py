"""
Cost guard (tiêu chí 8) — Theo dõi chi phí LLM theo ngày và tháng trong Redis.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
import redis

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_fallback_daily: dict[str, float] = {}
_fallback_monthly: dict[str, float] = {}


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _monthly_key() -> str:
    return f"cost:monthly:{datetime.now(timezone.utc).strftime('%Y-%m')}"


def _get_spend(redis_key: str, fallback: dict[str, float]) -> float:
    if r is None:
        return fallback.get(redis_key, 0.0)
    try:
        raw = r.get(redis_key)
        return float(raw) if raw is not None else 0.0
    except (redis.RedisError, ValueError) as exc:
        logger.warning("redis_cost_read_fallback", extra={"error": str(exc)})
        return fallback.get(redis_key, 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_spend = _get_spend(_daily_key(), _fallback_daily)
    if daily_spend >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "spent_usd": round(daily_spend, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )

    monthly_spend = _get_spend(_monthly_key(), _fallback_monthly)
    if monthly_spend >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "spent_usd": round(monthly_spend, 6),
                "budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng trong Redis, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    d_key = _daily_key()
    m_key = _monthly_key()

    if r is None:
        _fallback_daily[d_key] = _fallback_daily.get(d_key, 0.0) + cost
        _fallback_monthly[m_key] = _fallback_monthly.get(m_key, 0.0) + cost
        return cost

    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(d_key, cost)
        pipe.expire(d_key, 2 * 24 * 3600)
        pipe.incrbyfloat(m_key, cost)
        pipe.expire(m_key, 35 * 24 * 3600)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("redis_cost_write_fallback", extra={"error": str(exc)})
        _fallback_daily[d_key] = _fallback_daily.get(d_key, 0.0) + cost
        _fallback_monthly[m_key] = _fallback_monthly.get(m_key, 0.0) + cost

    return cost
