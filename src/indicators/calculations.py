"""
Consolidated Indicator Calculations.

This module provides single implementations for all technical indicator calculations,
eliminating code duplication across the codebase.

Version: 2.0.0, Last Updated: 2026-02-09, Status: Current
"""

import structlog

from .calc_modules._momentum import MomentumMixin
from .calc_modules._support_resistance import SupportResistanceMixin
from .calc_modules._trend import TrendMixin
from .calc_modules._volatility import VolatilityMixin
from .calc_modules._volume import VolumeMixin
from .utils import CoreCalculations

logger = structlog.get_logger(__name__)


class IndicatorCalculations(
    TrendMixin,
    MomentumMixin,
    VolatilityMixin,
    VolumeMixin,
    SupportResistanceMixin,
):
    """
    Consolidated indicator calculations.

    This class provides single implementations for all technical indicator calculations,
    eliminating code duplication across the codebase.
    """

    def __init__(self, backend: str = "auto"):
        """
        Initialize IndicatorCalculations.

        Args:
            backend: Backend to use ('talib', 'finta', or 'auto')
        """
        self.core = CoreCalculations()
        self.logger = logger

        # Initialize backend manager and detect best backend
        from .backend_manager import Backend, get_backend_manager

        self.backend_manager = get_backend_manager()
        self.backend_enum = self.backend_manager.detect_best_backend(backend)
        self.backend = self.backend_enum.value

        # Get backend modules
        if self.backend_enum == Backend.PANDAS_TA:
            self.pandas_ta = self.backend_manager.get_module(Backend.PANDAS_TA)
        elif self.backend_enum == Backend.TALIB:
            self.talib = self.backend_manager.get_module(Backend.TALIB)
        elif self.backend_enum == Backend.FINTA:
            self.TA = self.backend_manager.get_module(Backend.FINTA)

        logger.info(f"IndicatorCalculations initialized with {self.backend} backend")
