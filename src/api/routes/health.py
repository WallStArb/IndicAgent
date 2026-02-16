"""
Health Check Routes

System health monitoring endpoints.
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_db_manager, get_redis_manager

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "IndicAgent API",
        "version": "2.0.0-clean",
    }


@router.get("/database")
async def database_health(db_manager=Depends(get_db_manager)):
    """Database health check."""
    try:
        # Test database connection
        conn = await db_manager.connection_manager.get_connection()
        _ = await conn.fetchval("SELECT 1")
        await conn.close()

        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {str(e)}") from e


@router.get("/redis")
async def redis_health(redis_manager=Depends(get_redis_manager)):
    """Redis health check."""
    try:
        # Test Redis connection
        await redis_manager.redis_client.ping()

        return {
            "status": "healthy",
            "redis": "connected",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as e:
        logger.error("Redis health check failed", error=str(e))
        raise HTTPException(status_code=503, detail=f"Redis unhealthy: {str(e)}") from e


@router.get("/full")
async def full_health_check(
    db_manager=Depends(get_db_manager), redis_manager=Depends(get_redis_manager)
):
    """Comprehensive health check."""
    health_status = {
        "service": "IndicAgent API",
        "version": "2.0.0-clean",
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {},
    }

    # Check database
    try:
        conn = await db_manager.connection_manager.get_connection()
        await conn.fetchval("SELECT 1")
        await conn.close()
        health_status["components"]["database"] = "healthy"
    except Exception as e:
        health_status["components"]["database"] = f"unhealthy: {str(e)}"

    # Check Redis
    try:
        await redis_manager.redis_client.ping()
        health_status["components"]["redis"] = "healthy"
    except Exception as e:
        health_status["components"]["redis"] = f"unhealthy: {str(e)}"

    # Overall status
    all_healthy = all(status == "healthy" for status in health_status["components"].values())
    health_status["status"] = "healthy" if all_healthy else "degraded"

    if not all_healthy:
        raise HTTPException(status_code=503, detail=health_status)

    return health_status
