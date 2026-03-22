"""
Core Infrastructure Components

This module contains the foundational infrastructure:
- Database management with simplified interface
- Redis Streams for event-driven processing
- Core data models and types

All components are production-ready and focused.
"""

from .database_manager import DatabaseManager
from .models import DataSource, Timeframe
__all__ = ["Timeframe", "DataSource", "DatabaseManager"]
