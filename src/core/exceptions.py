from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
import uuid
from datetime import datetime
from typing import Any, Dict, Optional


class APIException(Exception):
    def __init__(self, status_code: int, detail: str, error_code: Optional[str] = None):
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code


class ShopifyAPIException(APIException):
    def __init__(self, detail: str, status_code: int = 500):
        super().__init__(status_code, detail, "SHOPIFY_API_ERROR")


class WooCommerceAPIException(APIException):
    def __init__(self, detail: str, status_code: int = 500):
        super().__init__(status_code, detail, "WOOCOMMERCE_API_ERROR")


class WhatsAppAPIException(APIException):
    def __init__(self, detail: str, status_code: int = 500):
        super().__init__(status_code, detail, "WHATSAPP_API_ERROR")


class OpenAIAPIException(APIException):
    def __init__(self, detail: str, status_code: int = 500):
        super().__init__(status_code, detail, "OPENAI_API_ERROR")


class RateLimitException(APIException):
    def __init__(self, detail: str = "Rate limit exceeded"):
        super().__init__(429, detail, "RATE_LIMIT_EXCEEDED")


class AuthenticationException(APIException):
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(401, detail, "AUTHENTICATION_FAILED")


class ValidationException(APIException):
    def __init__(self, detail: str):
        super().__init__(422, detail, "VALIDATION_ERROR")


async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    
    logger.error(f"API Exception: {exc.detail}", extra={
        "correlation_id": correlation_id,
        "status_code": exc.status_code,
        "error_code": exc.error_code,
        "path": str(request.url.path),
        "method": request.method
    })
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error_code": exc.error_code,
            "correlation_id": correlation_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    
    logger.error(f"Unhandled exception: {str(exc)}", extra={
        "correlation_id": correlation_id,
        "path": str(request.url.path),
        "method": request.method,
        "exception_type": type(exc).__name__
    })
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "correlation_id": correlation_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )