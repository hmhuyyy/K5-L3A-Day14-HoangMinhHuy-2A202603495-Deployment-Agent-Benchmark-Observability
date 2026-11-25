"""
Production AI Agent — Part 6 Final Project.

Đáp ứng đủ 12 tiêu chí production readiness:
  • GET /health (liveness) và GET /ready (readiness kiểm tra Redis)
  • POST /ask bảo vệ bởi X-API-Key, Redis rate limiting, và Redis cost guard
  • Structured JSON logging
  • Config từ biến môi trường (12-Factor)
  • Graceful shutdown (lifespan + SIGTERM forwarding)
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import sys
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mọi dòng log của app thành 1 JSON object hợp lệ."""

    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "environment": settings.environment,
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("agent")
    log.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    log.propagate = False
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        log.addHandler(handler)
    return log


logger = _setup_logger()
START_TIME = time.time()
_is_shutting_down = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_shutting_down
    _is_shutting_down = False

    # Đăng ký SIGTERM logger nhưng luôn gọi lại handler cũ của uvicorn để tắt an toàn
    if hasattr(signal, "SIGTERM"):
        previous_handler = signal.getsignal(signal.SIGTERM)

        def _on_sigterm(signum, frame):
            global _is_shutting_down
            _is_shutting_down = True
            logger.info("sigterm_received", extra={"signal": signum})
            if callable(previous_handler):
                previous_handler(signum, frame)

        try:
            signal.signal(signal.SIGTERM, _on_sigterm)
        except ValueError:
            pass

    logger.info(
        "agent_startup",
        extra={
            "port": settings.port,
            "rate_limit_per_minute": settings.rate_limit_per_minute,
            "daily_budget_usd": settings.daily_budget_usd,
        },
    )
    yield
    _is_shutting_down = True
    logger.info("agent_shutdown_begin")
    close_redis()
    logger.info("agent_shutdown_complete")


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "ms": elapsed_ms,
            },
        )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        "validation_error",
        extra={"path": request.url.path, "error_count": len(exc.errors())},
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "detail": [
                {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
                for err in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_exception",
        extra={"path": request.url.path, "error_type": type(exc).__name__},
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default="anonymous", max_length=100)


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn chạy, không phụ thuộc Redis."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/ready")
def ready():
    """Readiness probe: 200 khi sẵn sàng, 503 khi đang tắt hoặc Redis không kết nối được."""
    if _is_shutting_down:
        raise HTTPException(status_code=503, detail="Agent is shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis is not available")
    return {"status": "ready", "redis": "connected"}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = _estimate_tokens(body.question)
    output_tokens = _estimate_tokens(answer)
    cost_usd = record_cost(input_tokens, output_tokens)

    logger.info(
        "llm_call",
        extra={
            "user_id": body.user_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
        },
    )
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
        },
    }
