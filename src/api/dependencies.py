"""
API Dependencies

Shared dependency functions for FastAPI routes.
"""

from fastapi import HTTPException

# Global resources (set by main.py)
db_manager = None
config_service = None


async def get_db_manager():
    """Get database manager dependency."""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="Database manager not initialized")
    return db_manager


async def get_config_service():
    """Get the APR config service dependency (ui.dashboard.* keys)."""
    if config_service is None:
        raise HTTPException(status_code=503, detail="Config service not initialized")
    return config_service
