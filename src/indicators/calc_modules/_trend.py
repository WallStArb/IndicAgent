"""Trend indicator calculations mixin (MACD, Moving Averages)."""

from typing import Any

import pandas as pd


class TrendMixin:
    """Mixin providing trend indicator calculations."""

    def calculate_macd(
        self, df: pd.DataFrame, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
    ) -> dict[str, Any] | None:
        """
        Calculate MACD (Moving Average Convergence Divergence).

        Single implementation used by all modules.

        Args:
            df: DataFrame with OHLCV data
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line period

        Returns:
            Dictionary with MACD values or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=50):
            return None

        try:
            close = df["close"]

            if self.backend == "pandas_ta":
                # Use pandas-ta for MACD calculation
                macd_df = df.ta.macd(fast=fast_period, slow=slow_period, signal=signal_period)
                macd_line = macd_df[f"MACD_{fast_period}_{slow_period}_{signal_period}"].values
                signal_line = macd_df[f"MACDs_{fast_period}_{slow_period}_{signal_period}"].values
                histogram = macd_df[f"MACDh_{fast_period}_{slow_period}_{signal_period}"].values
            elif self.backend == "talib":
                # Use TA-Lib direct functions
                import talib

                macd_line, signal_line, histogram = talib.MACD(
                    close.values,
                    fastperiod=fast_period,
                    slowperiod=slow_period,
                    signalperiod=signal_period,
                )
            else:  # finta
                # Use finta with enhanced error handling
                try:
                    from finta import TA

                    macd_df = TA.MACD(df)
                    macd_line = macd_df["MACD"].values
                    signal_line = macd_df["SIGNAL"].values
                    histogram = macd_line - signal_line
                except Exception as e:
                    self.core.handle_calculation_error(e, "MACD (finta)")
                    return None

            # Calculate divergence strength
            price_change = close.pct_change(periods=10).iloc[-1]
            macd_change = pd.Series(macd_line).pct_change(periods=10).iloc[-1]

            # Divergence occurs when price and MACD move in opposite directions
            divergence_strength = 0.0
            if not pd.isna(price_change) and not pd.isna(macd_change):
                if (price_change > 0 and macd_change < 0) or (price_change < 0 and macd_change > 0):
                    divergence_strength = abs(price_change - macd_change)

            return {
                "macd": self.core.safe_float_conversion(macd_line[-1]),
                "signal": self.core.safe_float_conversion(signal_line[-1]),
                "histogram": self.core.safe_float_conversion(histogram[-1]),
                "divergence_strength": self.core.safe_float_conversion(divergence_strength),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "MACD")
            return None

    def calculate_macd_series(
        self,
        prices: pd.Series,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate MACD series for pattern detection.

        Args:
            prices: Price series (typically close prices)
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line period

        Returns:
            Tuple of (macd_line, signal_line, histogram)
        """
        try:
            # Try pandas-ta first
            import pandas_ta as ta

            macd_data = ta.macd(prices, fast=fast_period, slow=slow_period, signal=signal_period)
            macd_line = macd_data[f"MACD_{fast_period}_{slow_period}_{signal_period}"]
            signal_line = macd_data[f"MACDs_{fast_period}_{slow_period}_{signal_period}"]
            histogram = macd_data[f"MACDh_{fast_period}_{slow_period}_{signal_period}"]
        except ImportError:
            # Fallback manual calculation
            ema_fast = prices.ewm(span=fast_period).mean()
            ema_slow = prices.ewm(span=slow_period).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal_period).mean()
            histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def calculate_moving_averages(
        self, df: pd.DataFrame, periods: list = None
    ) -> dict[str, Any] | None:
        """
        Calculate Moving Averages.

        Single implementation used by all modules.

        Args:
            df: DataFrame with OHLCV data
            periods: List of periods to calculate

        Returns:
            Dictionary with Moving Average values or None if calculation fails
        """
        if periods is None:
            periods = [10, 20, 50, 100, 200]
        if not self.core.validate_dataframe(df, min_periods=50):
            return None

        try:
            close = df["close"]
            result = {}

            for period in periods:
                if not self.core.validate_period(period):
                    continue

                if self.backend == "pandas_ta":
                    # SMA
                    sma_values = df.ta.sma(length=period).values
                    result[f"sma_{period}"] = self.core.safe_float_conversion(sma_values[-1])

                    # EMA
                    ema_values = df.ta.ema(length=period).values
                    result[f"ema_{period}"] = self.core.safe_float_conversion(ema_values[-1])

                elif self.backend == "talib":
                    # SMA
                    sma_values = self.talib.SMA(close.values, timeperiod=period)
                    result[f"sma_{period}"] = self.core.safe_float_conversion(sma_values[-1])

                    # EMA
                    ema_values = self.talib.EMA(close.values, timeperiod=period)
                    result[f"ema_{period}"] = self.core.safe_float_conversion(ema_values[-1])

                else:  # finta
                    # SMA
                    sma_values = self.TA.SMA(df, period=period).values
                    result[f"sma_{period}"] = self.core.safe_float_conversion(sma_values[-1])

                    # EMA
                    ema_values = self.TA.EMA(df, period=period).values
                    result[f"ema_{period}"] = self.core.safe_float_conversion(ema_values[-1])

            return result

        except Exception as e:
            self.core.handle_calculation_error(e, "Moving Averages")
            return None

    def calculate_moving_averages_series(
        self, prices: pd.Series, periods: list = None
    ) -> dict[str, pd.Series]:
        """
        Calculate Moving Average series for pattern detection.

        Args:
            prices: Price series (typically close prices)
            periods: List of periods to calculate

        Returns:
            Dictionary of MA series
        """
        if periods is None:
            periods = [10, 20, 50, 100, 200]
        result = {}

        try:
            import pandas_ta as ta

            for period in periods:
                if not self.core.validate_period(period):
                    continue

                # SMA
                sma_series = ta.sma(prices, length=period)
                result[f"sma_{period}"] = sma_series

                # EMA
                ema_series = ta.ema(prices, length=period)
                result[f"ema_{period}"] = ema_series

        except ImportError:
            # Fallback manual calculation
            for period in periods:
                if not self.core.validate_period(period):
                    continue

                # SMA
                sma_series = prices.rolling(window=period).mean()
                result[f"sma_{period}"] = sma_series

                # EMA
                ema_series = prices.ewm(span=period).mean()
                result[f"ema_{period}"] = ema_series

        return result
