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
from fastapi.middleware.gzip import GZipMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from src.observability.metrics import API_HEALTH

from ..core import DatabaseManager
from . import dependencies
from .routes import (
    concepts,
    data,
    health,
    instruments,
    market_data,
    pipeline,
    research,
    system,
    universe,
    vocabulary,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
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

        # APR reader for the ui.dashboard.* keys the read routes apply, on the API's own pool
        from src.config.config_service import ConfigService

        dependencies.config_service = ConfigService(
            settings.database_url, pool=dependencies.db_manager.pool
        )
        await dependencies.config_service.initialize()

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
                    await dependencies.db_manager.upsert_instruments(instruments_to_seed)
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

# The dashboard's passport carries a name's full bar history (hundreds of kB of JSON).
# Level 6 against Starlette's default 9: a 554 kB passport compresses to within 2% of level 9 in a
# third of the time (28 ms against 77 ms), paid on every response including cache hits.
app.add_middleware(GZipMiddleware, compresslevel=6)

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
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(data.router, prefix="/api/data", tags=["data"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(universe.router, prefix="/api/universe", tags=["universe"])
app.include_router(concepts.router, prefix="/api/concepts", tags=["concepts"])
app.include_router(research.router, prefix="/api/research", tags=["research"])
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
