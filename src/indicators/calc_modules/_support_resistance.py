"""Support/Resistance and Pivot Point calculations mixin."""

from typing import Any

import numpy as np
import pandas as pd


class SupportResistanceMixin:
    """Mixin providing support/resistance and pivot point calculations."""

    def calculate_support_resistance(
        self, df: pd.DataFrame, window: int = 20, min_strength: int = 2
    ) -> dict[str, Any] | None:
        """
        Calculate Support and Resistance levels using pivot point analysis.

        Args:
            df: DataFrame with OHLCV data
            window: Window size for pivot detection
            min_strength: Minimum touches required for level validation

        Returns:
            Dictionary with support/resistance levels or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=50):
            return None

        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]

            # Find pivot highs and lows
            pivot_highs = []
            pivot_lows = []

            for i in range(window, len(df) - window):
                # Pivot high: highest point in window
                if high.iloc[i] == high.iloc[i - window : i + window + 1].max():
                    pivot_highs.append((i, high.iloc[i]))

                # Pivot low: lowest point in window
                if low.iloc[i] == low.iloc[i - window : i + window + 1].min():
                    pivot_lows.append((i, low.iloc[i]))

            # Cluster levels to find support/resistance
            resistance_levels = self._cluster_levels(
                [level for _, level in pivot_highs], close.iloc[-1]
            )
            support_levels = self._cluster_levels(
                [level for _, level in pivot_lows], close.iloc[-1]
            )

            # Current price for level classification
            current_price = close.iloc[-1]

            # Find nearest levels
            nearest_resistance = (
                min(resistance_levels, key=lambda x: abs(x - current_price))
                if resistance_levels
                else current_price * 1.02
            )
            nearest_support = (
                min(support_levels, key=lambda x: abs(x - current_price))
                if support_levels
                else current_price * 0.98
            )

            return {
                "current_price": self.core.safe_float_conversion(current_price),
                "nearest_resistance": self.core.safe_float_conversion(nearest_resistance),
                "nearest_support": self.core.safe_float_conversion(nearest_support),
                "resistance_strength": len(
                    [
                        r
                        for r in resistance_levels
                        if abs(r - nearest_resistance) < current_price * 0.001
                    ]
                ),
                "support_strength": len(
                    [s for s in support_levels if abs(s - nearest_support) < current_price * 0.001]
                ),
                "resistance_distance_pct": ((nearest_resistance - current_price) / current_price)
                * 100,
                "support_distance_pct": ((current_price - nearest_support) / current_price) * 100,
                "total_resistance_levels": len(resistance_levels),
                "total_support_levels": len(support_levels),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "Support Resistance")
            return None

    def _cluster_levels(
        self, levels: list, current_price: float, cluster_pct: float = 0.005
    ) -> list:
        """
        Cluster price levels that are close together.

        Args:
            levels: List of price levels
            current_price: Current market price for reference
            cluster_pct: Percentage threshold for clustering

        Returns:
            List of clustered levels
        """
        if not levels:
            return []

        levels = sorted(levels)
        clusters = []
        current_cluster = [levels[0]]

        for level in levels[1:]:
            if abs(level - current_cluster[-1]) <= current_price * cluster_pct:
                current_cluster.append(level)
            else:
                # Average the cluster and start new one
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [level]

        # Add final cluster
        if current_cluster:
            clusters.append(sum(current_cluster) / len(current_cluster))

        return clusters

    def calculate_pivot_points(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """
        Calculate Pivot Points (Classic, Woodie, Camarilla).

        Single implementation used by all modules.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dictionary with Pivot Point levels or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=2):
            return None

        try:
            # Use previous day's data for pivot calculation
            prev_high = df["high"].iloc[-2]
            prev_low = df["low"].iloc[-2]
            prev_close = df["close"].iloc[-2]

            # Classic Pivot Points
            pivot_point = (prev_high + prev_low + prev_close) / 3
            r1 = (2 * pivot_point) - prev_low
            s1 = (2 * pivot_point) - prev_high
            r2 = pivot_point + (prev_high - prev_low)
            s2 = pivot_point - (prev_high - prev_low)
            r3 = prev_high + 2 * (pivot_point - prev_low)
            s3 = prev_low - 2 * (prev_high - pivot_point)

            # Woodie Pivot Points
            woodie_pivot = (prev_high + prev_low + 2 * prev_close) / 4
            woodie_r1 = (2 * woodie_pivot) - prev_low
            woodie_s1 = (2 * woodie_pivot) - prev_high

            # Camarilla Pivot Points
            range_val = prev_high - prev_low
            camarilla_r1 = prev_close + (range_val * 1.1 / 12)
            camarilla_r2 = prev_close + (range_val * 1.1 / 6)
            camarilla_r3 = prev_close + (range_val * 1.1 / 4)
            camarilla_s1 = prev_close - (range_val * 1.1 / 12)
            camarilla_s2 = prev_close - (range_val * 1.1 / 6)
            camarilla_s3 = prev_close - (range_val * 1.1 / 4)

            return {
                # Classic Pivot Points (flattened)
                "classic_pivot": self.core.safe_float_conversion(pivot_point),
                "classic_r1": self.core.safe_float_conversion(r1),
                "classic_r2": self.core.safe_float_conversion(r2),
                "classic_r3": self.core.safe_float_conversion(r3),
                "classic_s1": self.core.safe_float_conversion(s1),
                "classic_s2": self.core.safe_float_conversion(s2),
                "classic_s3": self.core.safe_float_conversion(s3),
                # Woodie Pivot Points (flattened)
                "woodie_pivot": self.core.safe_float_conversion(woodie_pivot),
                "woodie_r1": self.core.safe_float_conversion(woodie_r1),
                "woodie_s1": self.core.safe_float_conversion(woodie_s1),
                # Camarilla Pivot Points (flattened)
                "camarilla_r1": self.core.safe_float_conversion(camarilla_r1),
                "camarilla_r2": self.core.safe_float_conversion(camarilla_r2),
                "camarilla_r3": self.core.safe_float_conversion(camarilla_r3),
                "camarilla_s1": self.core.safe_float_conversion(camarilla_s1),
                "camarilla_s2": self.core.safe_float_conversion(camarilla_s2),
                "camarilla_s3": self.core.safe_float_conversion(camarilla_s3),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "Pivot Points")
            return None

    def calculate_wma_series(self, prices: pd.Series, periods: list = None) -> dict[str, pd.Series]:
        """
        Calculate Weighted Moving Average series.

        Args:
            prices: Price series (typically close prices)
            periods: List of periods to calculate

        Returns:
            Dictionary of WMA series
        """
        if periods is None:
            periods = [10, 20, 50, 100, 200]
        result = {}

        try:
            import pandas_ta as ta

            for period in periods:
                if not self.core.validate_period(period):
                    continue

                # WMA
                wma_series = ta.wma(prices, length=period)
                result[f"wma_{period}"] = wma_series

        except ImportError:
            # Fallback manual calculation
            for period in periods:
                if not self.core.validate_period(period):
                    continue

                # Manual WMA calculation
                w = np.arange(1, period + 1)
                wma_series = prices.rolling(window=period).apply(
                    lambda x, weights=w: np.average(x, weights=weights), raw=True
                )
                result[f"wma_{period}"] = wma_series

        return result

    def calculate_vwma_series(
        self, prices: pd.Series, volume: pd.Series, periods: list = None
    ) -> dict[str, pd.Series]:
        """
        Calculate Volume Weighted Moving Average series.

        Args:
            prices: Price series (typically close prices)
            volume: Volume series
            periods: List of periods to calculate

        Returns:
            Dictionary of VWMA series
        """
        if periods is None:
            periods = [10, 20, 50, 100, 200]
        result = {}

        try:
            import pandas_ta as ta

            for period in periods:
                if not self.core.validate_period(period):
                    continue

                # VWMA
                vwma_series = ta.vwma(prices, volume, length=period)
                result[f"vwma_{period}"] = vwma_series

        except ImportError:
            # Fallback manual calculation
            for period in periods:
                if not self.core.validate_period(period):
                    continue

                # Manual VWMA calculation
                vwma_series = (prices * volume).rolling(window=period).sum() / volume.rolling(
                    window=period
                ).sum()
                result[f"vwma_{period}"] = vwma_series

        return result
