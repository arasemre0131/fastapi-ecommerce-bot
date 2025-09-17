import redis
import uuid
import time
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from loguru import logger
from typing import Callable
from .config import settings


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()
        correlation_id = getattr(request.state, "correlation_id", "unknown")
        
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "query_params": str(request.query_params)
            }
        )
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        logger.info(
            f"Request completed: {request.method} {request.url.path} - {response.status_code}",
            extra={
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "process_time": process_time
            }
        )
        
        response.headers["X-Process-Time"] = str(process_time)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, calls: int = None, period: int = None):
        super().__init__(app)
        self.calls = calls or settings.rate_limit_calls
        self.period = period or settings.rate_limit_period
        try:
            self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        except Exception as e:
            logger.error(f"Redis connection failed for rate limiting: {e}")
            self.redis = None
    
    async def dispatch(self, request: Request, call_next: Callable):
        if not self.redis:
            return await call_next(request)
        
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/", "/docs", "/redoc"]:
            return await call_next(request)
        
        client_ip = self._get_client_ip(request)
        key = f"rate_limit:{client_ip}"
        
        try:
            current_calls = self.redis.get(key)
            if current_calls is None:
                self.redis.setex(key, self.period, 1)
            else:
                current_calls = int(current_calls)
                if current_calls >= self.calls:
                    logger.warning(
                        f"Rate limit exceeded for {client_ip}",
                        extra={"client_ip": client_ip, "calls": current_calls}
                    )
                    return JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={
                            "detail": "Rate limit exceeded",
                            "error_code": "RATE_LIMIT_EXCEEDED"
                        },
                        headers={"Retry-After": str(self.period)}
                    )
                self.redis.incr(key)
        except redis.RedisError as e:
            logger.error(f"Redis error in rate limiting: {e}")
        
        return await call_next(request)
    
    def _get_client_ip(self, request: Request) -> str:
        # Check for forwarded headers (common in production)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        return response