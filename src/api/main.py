"""
IndicAgent FastAPI Main Application

Clean, focused API for technical indicators and market data.
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core import DatabaseManager
from . import dependencies
from .routes import drift, features, health, indicators, instruments, market_data, signals, sse

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    _broadcaster_task = None
    _sse_consumer = None
    try:
        # Initialize core infrastructure
        logger.info("Starting IndicAgent API...")

        # Initialize database manager
        from src.config.settings import Settings

        settings = Settings()
        dependencies.db_manager = DatabaseManager(settings.database_url)
        await dependencies.db_manager.initialize()

        # Initialize Kafka SSE broadcaster
        from src.core.kafka_utils import KafkaConsumerClient
        from src.core.stream_keys import (
            topic_indicators,
            topic_intelligence,
            topic_intelligence_i8,
            topic_intelligence_journal,
            topic_market_bars,
            topic_market_bars_htf,
            topic_market_ticks,
            topic_narratives,
            topic_narratives_group,
            topic_signals_aggregated,
        )

        from .routes.sse import KafkaSSEBroadcaster

        kafka_bootstrap = settings.kafka_bootstrap_servers
        env_name = settings.env_name or ""

        dependencies.kafka_broadcaster = KafkaSSEBroadcaster()
        _sse_consumer = KafkaConsumerClient(
            topic_market_ticks(env_name),
            topic_market_bars(env_name),
            topic_market_bars_htf(env_name),
            topic_indicators(env_name),
            topic_intelligence(env_name),
            topic_intelligence_journal(env_name),
            topic_intelligence_i8(env_name),
            topic_signals_aggregated(env_name),
            topic_narratives(env_name),
            topic_narratives_group(env_name),
            bootstrap_servers=kafka_bootstrap,
            # Single-instance group: every API process must receive all messages for SSE.
            # latest offset: skip history, only deliver live messages to clients.
            group_id="sse_broadcaster",
            auto_offset_reset="latest",
        )
        await _sse_consumer.start()
        await _sse_consumer.seek_to_end()  # always skip committed history; start from live
        _broadcaster_task = asyncio.create_task(dependencies.kafka_broadcaster.run(_sse_consumer))

        # Seed instruments table from contract config
        await dependencies.db_manager.upsert_instruments(settings.contracts)

        logger.info("IndicAgent API started successfully")
        yield

    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    finally:
        # Cleanup
        if _broadcaster_task is not None:
            _broadcaster_task.cancel()
            try:
                await _broadcaster_task
            except Exception:
                pass
        if _sse_consumer is not None:
            try:
                await _sse_consumer.stop()
            except Exception:
                pass
        if dependencies.db_manager:
            await dependencies.db_manager.close()
        logger.info("Application shutdown complete")


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
app.include_router(drift.router, prefix="/api/drift", tags=["drift"])


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
