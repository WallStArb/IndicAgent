"""
IndicAgent FastAPI Main Application

Clean, focused API for technical indicators and market data.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core import DatabaseManager, RedisStreamsManager
from . import dependencies
from .routes import health, indicators, instruments, market_data, sse, features, signals

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    try:
        # Initialize core infrastructure
        logger.info("Starting IndicAgent API...")

        # Initialize database manager
        from src.config.settings import Settings

        settings = Settings()
        dependencies.db_manager = DatabaseManager(settings.database_url)
        await dependencies.db_manager.initialize()

        # Initialize Redis streams manager
        import redis.asyncio as redis

        # Build Redis client from individual settings
        redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
        )
        dependencies.redis_manager = RedisStreamsManager(redis_client)
        await dependencies.redis_manager.start()

        # Seed instruments table from contract config
        await dependencies.db_manager.upsert_instruments(settings.contracts)

        logger.info("✅ IndicAgent API started successfully")
        yield

    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    finally:
        # Cleanup
        if dependencies.redis_manager:
            await dependencies.redis_manager.stop()
        if dependencies.db_manager:
            await dependencies.db_manager.close()
        logger.info("✅ Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="IndicAgent API",
    description="Market Intelligence & Technical Analysis Platform",
    version="2.0.0-clean",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(indicators.router, prefix="/indicators", tags=["indicators"])
app.include_router(market_data.router, prefix="/api", tags=["market-data"])
app.include_router(instruments.router, prefix="/api", tags=["instruments"])
app.include_router(sse.router, prefix="/api/sse", tags=["sse"])
app.include_router(features.router, prefix="/api", tags=["features"])
app.include_router(signals.router, prefix="/api", tags=["signals"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "IndicAgent API",
        "version": "2.0.0-clean",
        "status": "production-ready",
        "description": "Market Intelligence & Technical Analysis Platform",
    }


# Standards-compliant health and metrics endpoints
@app.get("/health")
async def health():
    """Standards-compliant health endpoint."""
    from datetime import UTC, datetime

    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "IndicAgent API",
    }


@app.get("/metrics")
async def metrics():
    """Standards-compliant metrics endpoint."""
    from fastapi.responses import Response
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    # Return Prometheus metrics
    metrics_output = generate_latest()
    return Response(content=metrics_output, media_type=CONTENT_TYPE_LATEST)
