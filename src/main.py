from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
import sys

from .core.config import settings
from .core.exceptions import (
    APIException, 
    api_exception_handler, 
    general_exception_handler
)
from .core.middleware import (
    CorrelationIDMiddleware,
    RequestLoggingMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting E-Commerce Support Bot API")
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format=settings.log_format,
        colorize=True
    )
    
    # Test database connection
    from .core.database import check_database_connection
    if await check_database_connection():
        logger.info("Database connection successful")
    else:
        logger.error("Database connection failed")
    
    yield
    
    # Shutdown
    logger.info("Shutting down E-Commerce Support Bot API")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Production-ready e-commerce support bot with AI capabilities",
    lifespan=lifespan,
    debug=settings.debug
)

# Add middleware (order matters!)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIDMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handlers
app.add_exception_handler(APIException, api_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Include routers
from .auth.router import router as auth_router
from .integrations.shopify.router import router as shopify_router

app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(shopify_router, prefix=settings.api_v1_prefix)


@app.get("/")
async def root():
    return {
        "message": "E-Commerce Support Bot API",
        "version": settings.version,
        "environment": settings.environment
    }


@app.get("/health")
async def health_check():
    from .core.database import check_database_connection
    
    health_status = {
        "status": "healthy",
        "timestamp": "2023-01-01T00:00:00Z",
        "version": settings.version,
        "environment": settings.environment,
        "checks": {
            "database": await check_database_connection(),
            "redis": True,  # Will implement Redis check
            "external_apis": True  # Will implement external API checks
        }
    }
    
    # Overall health status
    all_healthy = all(health_status["checks"].values())
    health_status["status"] = "healthy" if all_healthy else "unhealthy"
    
    from datetime import datetime
    health_status["timestamp"] = datetime.utcnow().isoformat()
    
    return health_status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )