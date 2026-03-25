"""
Shared utilities for production scripts.

Provides common patterns used across production scripts,
primarily database connection management.
"""

from __future__ import annotations

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager


async def get_script_db(settings: Settings | None = None) -> DatabaseManager:
    """Create and initialize a DatabaseManager for production scripts.

    Usage:
        settings = Settings()
        db = await get_script_db(settings)
        try:
            async with db.get_connection() as conn:
                ...
        finally:
            await db.close()
    """
    if settings is None:
        settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    return db
