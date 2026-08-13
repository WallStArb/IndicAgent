"""
Core Infrastructure Components

This module contains the foundational infrastructure:
- Database management with simplified interface
- Kafka/Redpanda event-driven streaming utilities
- Core data models and types

All components are production-ready and focused.
"""

from .database_manager import DatabaseManager
from .models import Timeframe

__all__ = ["Timeframe", "DatabaseManager"]
