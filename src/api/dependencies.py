"""
API Dependencies

Shared dependency functions for FastAPI routes.
"""

from fastapi import HTTPException

# Global resources (set by main.py)
db_manager = None
redis_manager = None


async def get_db_manager():
    """Get database manager dependency."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="Database manager not initialized")
    return db_manager


async def get_redis_manager():
    """Get Redis manager dependency."""
    if redis_manager is None:
        raise HTTPException(status_code=503, detail="Redis manager not initialized")
    return redis_manager
