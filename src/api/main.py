"""
IndicAgent FastAPI Main Application

Clean, focused API for technical indicators and market data.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from src.observability.metrics import API_HEALTH

from ..core import DatabaseManager
from . import dependencies
from .routes import (
    ai_stats,
    drift,
    features,
    health,
    instruments,
    market_data,
    narrative,
    signals,
    sse,
    validation,
    vocabulary,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    _broadcaster_task = None
    _sse_consumer = None
    _api_health_task = None
    try:
        # Initialize core infrastructure
        logger.info("Starting IndicAgent API...")

        # Initialize database manager
        from src.config.settings import Settings

        settings = Settings()
        dependencies.db_manager = DatabaseManager(settings.database_url)
        await dependencies.db_manager.initialize()

        # Background task: refresh api_health gauge every 30s independent of HTTP traffic
        async def _refresh_api_health() -> None:
            """Update api_health gauge + send systemd WATCHDOG=1 every 30s."""
            import sdnotify

            notifier = sdnotify.SystemdNotifier()
            while True:
                try:
                    async with dependencies.db_manager.get_connection() as conn:
                        await conn.fetchval("SELECT 1")
                    API_HEALTH.set(1, {"service": "indicagent-api"})
                except Exception as e:
                    API_HEALTH.set(0, {"service": "indicagent-api"})
                    logger.warning("api.health_refresh.db_unreachable", error=str(e))
                notifier.notify("WATCHDOG=1")
                await asyncio.sleep(30)

        _api_health_task = asyncio.create_task(_refresh_api_health())

        # Initialize Kafka SSE broadcaster
        from src.core.kafka_utils import KafkaConsumerClient
        from src.core.stream_keys import (
            topic_intelligence,
            topic_intelligence_i8,
            topic_intelligence_journal,
            topic_market_bars,
            topic_market_bars_htf,
            topic_narratives,
            topic_narratives_group,
            topic_signals_aggregated,
        )

        from .routes.sse import KafkaSSEBroadcaster

        kafka_bootstrap = settings.kafka_bootstrap_servers
        env_name = settings.env_name or ""

        dependencies.kafka_broadcaster = KafkaSSEBroadcaster()
        _sse_consumer = KafkaConsumerClient(
            topic_market_bars(env_name),
            topic_market_bars_htf(env_name),
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

        # Seed instruments table on empty cold-start only (count-gated, idempotent)
        count_rows = await dependencies.db_manager.execute_query(
            "SELECT COUNT(*) FROM instruments WHERE is_active = true"
        )
        instrument_count = count_rows[0]["count"] if count_rows else 0
        if instrument_count > 0:
            logger.info(
                "api.startup.instruments_db_already_seeded",
                count=instrument_count,
            )
        else:
            contracts_json_raw = os.environ.get("IBKR_CONTRACTS_JSON", "")
            if not contracts_json_raw:
                logger.warning("api.startup.instruments_seed_skipped_no_env")
            else:
                try:
                    from src.core.models import Instrument

                    parsed = json.loads(contracts_json_raw)
                    instruments_to_seed = [Instrument(**item) for item in parsed]
                    await dependencies.db_manager.upsert_instruments(
                        instruments=instruments_to_seed
                    )
                    logger.info(
                        "api.startup.instruments_seeded",
                        count=len(instruments_to_seed),
                    )
                except Exception as seed_exc:
                    logger.warning(
                        "api.startup.instruments_seed_parse_failed",
                        error=str(seed_exc),
                    )

        logger.info("IndicAgent API started successfully")
        yield

    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    finally:
        # Cleanup
        if _api_health_task is not None:
            _api_health_task.cancel()
            try:
                await _api_health_task
            except (asyncio.CancelledError, Exception):
                pass
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

# Wire OTel HTTP instrumentation: auto-emits rate/error/latency for every route
FastAPIInstrumentor().instrument_app(app)

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
app.include_router(market_data.router, prefix="/api", tags=["market-data"])
app.include_router(instruments.router, prefix="/api", tags=["instruments"])
app.include_router(sse.router, prefix="/api/sse", tags=["sse"])
app.include_router(features.router, prefix="/api", tags=["features"])
app.include_router(signals.router, prefix="/api", tags=["signals"])
app.include_router(narrative.router, prefix="/api", tags=["narrative"])
app.include_router(ai_stats.router, prefix="/api", tags=["ai"])
app.include_router(drift.router, prefix="/api/drift", tags=["drift"])
app.include_router(validation.router, prefix="/api/validation", tags=["validation"])
app.include_router(vocabulary.router, prefix="/api/vocabulary", tags=["vocabulary"])


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
    """Metrics are served by the OTel Collector at :8889/metrics (Prometheus format).

    Returns a 404 with guidance — callers should scrape the Collector directly.
    Prometheus job config: http://localhost:8889/metrics
    """
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=404,
        content={
            "detail": "Metrics are served by the OTel Collector at :8889/metrics",
            "prometheus_url": "http://localhost:8889/metrics",
        },
    )
