"""
Core Calculation Utilities.

This module provides core calculation utilities and validation functions
that are shared across all calculation modules.

Version: 1.0.0, Last Updated: 2025-08-01, Status: Current ✅
"""

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


class CoreCalculations:
    """
    Core calculation utilities and validation functions.

    This class provides shared utilities for all calculation modules,
    including data validation, error handling, and common calculation patterns.
    """

    def __init__(self):
        """Initialize CoreCalculations."""
        self.logger = logger

    def validate_dataframe(self, df: pd.DataFrame, min_periods: int = 50) -> bool:
        """
        Validate DataFrame for calculation requirements.

        Args:
            df: DataFrame to validate
            min_periods: Minimum number of periods required

        Returns:
            True if DataFrame is valid, False otherwise
        """
        if df is None or df.empty:
            self.logger.warning("DataFrame is None or empty")
            return False

        if len(df) < min_periods:
            self.logger.warning(f"DataFrame has {len(df)} rows, need at least {min_periods}")
            return False

        required_columns = ["open", "high", "low", "close", "volume"]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            self.logger.warning(f"Missing required columns: {missing_columns}")
            return False

        return True

    def handle_calculation_error(self, error: Exception, calculation_name: str) -> None:
        """
        Handle calculation errors consistently.

        Args:
            error: The exception that occurred
            calculation_name: Name of the calculation that failed
        """
        self.logger.error(f"Error in {calculation_name}: {str(error)}")

    def safe_float_conversion(
        self, value: float | np.float64 | None, default: float = 0.0
    ) -> float:
        """
        Safely convert value to float with optional default.

        Args:
            value: Value to convert
            default: Default value if conversion fails

        Returns:
            Float value or default if conversion fails
        """
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def calculate_percentage_change(self, current: float, previous: float) -> float:
        """
        Calculate percentage change between two values.

        Args:
            current: Current value
            previous: Previous value

        Returns:
            Percentage change as float
        """
        if previous == 0:
            return 0.0
        return ((current - previous) / previous) * 100

    def calculate_slope(self, y_values: np.ndarray, x_values: np.ndarray) -> float:
        """
        Calculate slope of a line using linear regression.

        Args:
            y_values: Y values
            x_values: X values

        Returns:
            Slope as float
        """
        if len(y_values) < 2 or len(x_values) < 2:
            return 0.0

        try:
            slope = np.polyfit(x_values, y_values, 1)[0]
            return float(slope)
        except Exception:
            return 0.0

    def normalize_value(self, value: float, min_val: float, max_val: float) -> float:
        """
        Normalize value to range [0, 1].

        Args:
            value: Value to normalize
            min_val: Minimum value in range
            max_val: Maximum value in range

        Returns:
            Normalized value between 0 and 1
        """
        if max_val == min_val:
            return 0.5
        return (value - min_val) / (max_val - min_val)

    def calculate_confidence_score(self, factors: dict[str, float]) -> float:
        """
        Calculate confidence score from multiple factors.

        Args:
            factors: Dictionary of factor names and their scores (0-1)

        Returns:
            Weighted confidence score (0-1)
        """
        if not factors:
            return 0.0

        # Default weights if not specified
        weights = {"strength": 0.3, "confluence": 0.3, "volume": 0.2, "trend": 0.2}

        total_score = 0.0
        total_weight = 0.0

        for factor_name, score in factors.items():
            weight = weights.get(factor_name, 0.1)
            total_score += score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        return total_score / total_weight

    def validate_period(self, period: int, min_period: int = 1, max_period: int = 500) -> bool:
        """
        Validate calculation period.

        Args:
            period: Period to validate
            min_period: Minimum allowed period
            max_period: Maximum allowed period

        Returns:
            True if period is valid, False otherwise
        """
        return min_period <= period <= max_period

    def calculate_rolling_statistics(
        self, series: pd.Series, window: int, stat_type: str = "mean"
    ) -> pd.Series:
        """
        Calculate rolling statistics with error handling.

        Args:
            series: Series to calculate statistics for
            window: Rolling window size
            stat_type: Type of statistic ('mean', 'std', 'min', 'max')

        Returns:
            Rolling statistics series
        """
        if not self.validate_period(window):
            return pd.Series([np.nan] * len(series))

        try:
            if stat_type == "mean":
                return series.rolling(window=window).mean()
            elif stat_type == "std":
                return series.rolling(window=window).std()
            elif stat_type == "min":
                return series.rolling(window=window).min()
            elif stat_type == "max":
                return series.rolling(window=window).max()
            else:
                return series.rolling(window=window).mean()
        except Exception as e:
            self.handle_calculation_error(e, f"rolling_{stat_type}")
            return pd.Series([np.nan] * len(series))
