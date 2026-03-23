"""
API Dependencies

Shared dependency functions for FastAPI routes.
"""

from fastapi import HTTPException

# Global resources (set by main.py)
db_manager = None
kafka_broadcaster = None


async def get_db_manager():
    """Get database manager dependency."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="Database manager not initialized")
    return db_manager


async def get_kafka_broadcaster():
    """Get Kafka SSE broadcaster dependency."""
    if kafka_broadcaster is None:
        raise HTTPException(status_code=503, detail="Kafka broadcaster not initialized")
    return kafka_broadcaster
