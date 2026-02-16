"""
Technical Analysis Indicators

Production-ready technical analysis system with:
- 15+ consolidated indicator calculations
- Multi-backend support (TA-lib → pandas-ta → finta)
- Optimized performance and error handling
- Type-safe implementations

Key Features:
- Single source of truth for all indicators
- Intelligent backend fallbacks
- Comprehensive validation and error handling
"""

from .backend_manager import Backend, get_backend_manager
from .calculations import IndicatorCalculations

__all__ = ["IndicatorCalculations", "get_backend_manager", "Backend"]
