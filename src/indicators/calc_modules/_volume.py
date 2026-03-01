"""Volume indicator calculations mixin (VWAP, MFI, OBV, Volume Profile, A/D Line)."""

from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.utils import clamp


class VolumeMixin:
    """Mixin providing volume indicator calculations."""

    def calculate_vwap(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """
        Calculate VWAP (Volume Weighted Average Price).

        Single implementation used by all modules.

        VWAP is a trading benchmark that gives average price weighted by volume:
        - Shows fair value based on volume
        - Acts as dynamic support/resistance
        - Excellent for institutional trading
        - Resets daily (for intraday use)

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dictionary with VWAP values or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=10):
            return None

        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            volume = df["volume"]

            # Calculate typical price
            typical_price = (high + low + close) / 3

            # Calculate VWAP
            cumulative_tp_volume = (typical_price * volume).cumsum()
            cumulative_volume = volume.cumsum()
            vwap = cumulative_tp_volume / cumulative_volume

            # Current values
            current_vwap = self.core.safe_float_conversion(vwap.iloc[-1], default=close.iloc[-1])
            current_price = self.core.safe_float_conversion(close.iloc[-1], default=0.0)

            # VWAP analysis
            price_vs_vwap = (
                ((current_price - current_vwap) / current_vwap) * 100 if current_vwap != 0 else 0.0
            )
            vwap_trend = self._detect_vwap_trend(vwap)

            # Volume-based signals
            recent_volume = volume.iloc[-5:].mean()
            avg_volume = volume.mean()
            volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0

            return {
                "vwap": current_vwap,
                "current_price": current_price,
                "price_vs_vwap_pct": self.core.safe_float_conversion(price_vs_vwap, default=0.0),
                "vwap_trend": vwap_trend,
                "volume_ratio": self.core.safe_float_conversion(volume_ratio, default=1.0),
                "above_vwap": current_price > current_vwap,
                "volume_significance": (
                    "high" if volume_ratio > 1.5 else "normal" if volume_ratio > 0.8 else "low"
                ),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "VWAP")
            return None

    def _detect_vwap_trend(self, vwap_series) -> str:
        """
        Detect VWAP trend.

        Args:
            vwap_series: VWAP values series

        Returns:
            Trend description
        """
        if len(vwap_series) < 5:
            return "unclear"

        recent = vwap_series.iloc[-5:]
        slope = (recent.iloc[-1] - recent.iloc[0]) / len(recent)
        avg_price = recent.mean()
        slope_pct = (slope / avg_price) * 100 if avg_price > 0 else 0

        if slope_pct > 0.1:
            return "rising"
        elif slope_pct < -0.1:
            return "falling"
        else:
            return "sideways"

    def calculate_mfi(self, df: pd.DataFrame, period: int = 14) -> dict[str, Any] | None:
        """
        Calculate MFI (Money Flow Index) - Volume-weighted RSI.

        Single implementation used by all modules.

        MFI combines price and volume to measure buying/selling pressure.
        It's often called "Volume-weighted RSI" and is excellent for:
        - Overbought/oversold conditions with volume confirmation
        - Divergence analysis (price vs volume-weighted momentum)
        - Volume-price relationship validation
        - Institutional money flow detection

        Args:
            df: DataFrame with OHLCV data
            period: MFI period (default 14)

        Returns:
            Dictionary with MFI values or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=20):
            return None

        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            volume = df["volume"]

            if self.backend == "pandas_ta":
                # Use pandas-ta for volume indicators with enhanced API usage
                mfi_14 = df.ta.mfi(length=14, append=True)["MFI_14"].values
                mfi_10 = df.ta.mfi(length=10, append=True)["MFI_10"].values
                mfi_20 = df.ta.mfi(length=20, append=True)["MFI_20"].values
            elif self.backend == "talib":
                # Standard MFI calculation (14-period default) - ensure proper data types
                mfi_14 = self.talib.MFI(
                    high.astype(np.float64).values,
                    low.astype(np.float64).values,
                    close.astype(np.float64).values,
                    volume.astype(np.float64).values,
                    timeperiod=14,
                )
                mfi_10 = self.talib.MFI(
                    high.astype(np.float64).values,
                    low.astype(np.float64).values,
                    close.astype(np.float64).values,
                    volume.astype(np.float64).values,
                    timeperiod=10,
                )
                mfi_20 = self.talib.MFI(
                    high.astype(np.float64).values,
                    low.astype(np.float64).values,
                    close.astype(np.float64).values,
                    volume.astype(np.float64).values,
                    timeperiod=20,
                )
            else:  # finta fallback
                mfi_14 = self._calculate_manual_mfi(df, period=14).values
                mfi_10 = self._calculate_manual_mfi(df, period=10).values
                mfi_20 = self._calculate_manual_mfi(df, period=20).values

            # Current MFI values
            current_mfi_14 = self.core.safe_float_conversion(mfi_14[-1], default=50.0)
            current_mfi_10 = self.core.safe_float_conversion(mfi_10[-1], default=50.0)
            current_mfi_20 = self.core.safe_float_conversion(mfi_20[-1], default=50.0)

            # Previous MFI values for trend analysis
            prev_mfi_14 = (
                self.core.safe_float_conversion(mfi_14[-2], default=current_mfi_14)
                if len(mfi_14) > 1
                else current_mfi_14
            )

            # MFI signals and interpretation
            signals = []
            if current_mfi_14 > 80:
                signals.append("overbought")
            elif current_mfi_14 < 20:
                signals.append("oversold")

            if current_mfi_14 > prev_mfi_14:
                signals.append("bullish_momentum")
            elif current_mfi_14 < prev_mfi_14:
                signals.append("bearish_momentum")

            # Convert signals list to string for TechnicalIndicator compatibility
            signals_str = ", ".join(signals) if signals else "neutral"

            return {
                "mfi_14": current_mfi_14,
                "mfi_10": current_mfi_10,
                "mfi_20": current_mfi_20,
                "mfi_trend": "up" if current_mfi_14 > prev_mfi_14 else "down",
                "mfi_signals": signals_str,
                "mfi_interpretation": self._interpret_mfi(current_mfi_14, prev_mfi_14),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "MFI")
            return None

    def calculate_volume_profile(self, df: pd.DataFrame, bins: int = 20) -> dict[str, Any] | None:
        """
        Calculate Volume Profile - Volume distribution by price levels.

        Args:
            df: DataFrame with OHLCV data
            bins: Number of price bins for volume distribution

        Returns:
            Dictionary with volume profile data or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=20):
            return None

        try:
            # Calculate price bins
            price_min = df["low"].min()
            price_max = df["high"].max()
            price_bins = pd.cut(df["close"], bins=bins)

            # Volume by price level
            volume_by_price = df.groupby(price_bins)["volume"].sum()

            # Volume weighted average price
            vwap = (df["close"] * df["volume"]).sum() / df["volume"].sum()

            # Point of control (price level with highest volume)
            poc_price = volume_by_price.idxmax()
            poc_volume = volume_by_price.max()

            return {
                "vwap": self.core.safe_float_conversion(vwap),
                "poc_price_range": str(poc_price) if poc_price else "N/A",
                "poc_volume": self.core.safe_float_conversion(poc_volume),
                "price_range_min": self.core.safe_float_conversion(price_min),
                "price_range_max": self.core.safe_float_conversion(price_max),
                "total_volume": self.core.safe_float_conversion(df["volume"].sum()),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "Volume Profile")
            return None

    def _calculate_manual_mfi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Manual MFI calculation for fallback compatibility.

        MFI = 100 - (100 / (1 + Money Flow Ratio))
        Money Flow Ratio = Positive Money Flow / Negative Money Flow
        """
        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            volume = df["volume"]

            # Typical Price
            tp = (high + low + close) / 3

            # Raw Money Flow
            rmf = tp * volume

            # Positive and Negative Money Flow
            pmf = pd.Series(index=df.index, dtype=float)
            nmf = pd.Series(index=df.index, dtype=float)

            for i in range(1, len(df)):
                if tp.iloc[i] > tp.iloc[i - 1]:
                    pmf.iloc[i] = rmf.iloc[i]
                    nmf.iloc[i] = 0
                elif tp.iloc[i] < tp.iloc[i - 1]:
                    pmf.iloc[i] = 0
                    nmf.iloc[i] = rmf.iloc[i]
                else:
                    pmf.iloc[i] = 0
                    nmf.iloc[i] = 0

            # Sum over period
            pmf_sum = pmf.rolling(window=period).sum()
            nmf_sum = nmf.rolling(window=period).sum()

            # MFI calculation
            mfi = 100 - (100 / (1 + (pmf_sum / nmf_sum.replace(0, 1))))

            return mfi.fillna(50)

        except Exception as e:
            self.logger.error(f"Error in manual MFI calculation: {e}")
            return pd.Series(index=df.index, data=50)

    def _interpret_mfi(self, current: float, previous: float) -> str:
        """
        Interpret MFI values and trends.

        Args:
            current: Current MFI value
            previous: Previous MFI value

        Returns:
            Interpretation string
        """
        if current > 80:
            return "overbought"
        elif current < 20:
            return "oversold"
        elif current > previous:
            return "bullish_momentum"
        elif current < previous:
            return "bearish_momentum"
        else:
            return "neutral"

    def calculate_enhanced_obv(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """
        Calculate Enhanced OBV with divergence detection and signal strength.

        Single implementation used by all modules.

        This enhanced version provides:
        - Standard OBV calculation
        - OBV trend analysis (short and long-term)
        - Divergence detection between price and OBV
        - Signal strength scoring
        - Volume-price relationship assessment

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dictionary with enhanced OBV analysis or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=30):
            return None

        try:
            close = df["close"]
            volume = df["volume"]

            # Calculate OBV using multiple methods for reliability
            if self.backend == "pandas_ta":
                obv_values = df.ta.obv(append=True)["OBV"].values
            elif self.backend == "talib":
                obv_values = self.talib.OBV(
                    close.astype(np.float64).values, volume.astype(np.float64).values
                )
            else:
                # Manual calculation as fallback
                obv_series = self._calculate_manual_obv(close, volume)
                obv_values = obv_series.values

            current_obv = self.core.safe_float_conversion(obv_values[-1], default=0.0)

            # OBV trend analysis
            obv_series = pd.Series(obv_values, index=df.index)
            obv_ma_short = obv_series.rolling(window=10).mean()
            obv_ma_long = obv_series.rolling(window=20).mean()

            current_ma_short = self.core.safe_float_conversion(
                obv_ma_short.iloc[-1], default=current_obv
            )
            current_ma_long = self.core.safe_float_conversion(
                obv_ma_long.iloc[-1], default=current_obv
            )

            # Divergence detection (simplified)
            price_trend = self._calculate_trend_strength(close, periods=20)
            obv_trend = self._calculate_trend_strength(obv_series, periods=20)

            # Signal strength analysis
            signal_strength = self._calculate_obv_signal_strength(close, obv_series, volume)

            return {
                "obv": current_obv,
                "obv_ma_short": current_ma_short,
                "obv_ma_long": current_ma_long,
                "obv_trend": "bullish" if current_ma_short > current_ma_long else "bearish",
                "price_trend_strength": price_trend,
                "obv_trend_strength": obv_trend,
                "divergence_detected": abs(price_trend - obv_trend) > 0.3,
                "signal_strength": signal_strength,
                "obv_interpretation": self._interpret_obv_signals(
                    current_obv, current_ma_short, current_ma_long, signal_strength
                ),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "Enhanced OBV")
            return None

    def _calculate_manual_obv(self, close: pd.Series, volume: pd.Series) -> pd.Series:
        """
        Manual OBV calculation for fallback compatibility.

        Args:
            close: Close price series
            volume: Volume series

        Returns:
            OBV series
        """
        try:
            obv = pd.Series(index=close.index, dtype=float)
            obv.iloc[0] = volume.iloc[0]

            for i in range(1, len(close)):
                if close.iloc[i] > close.iloc[i - 1]:
                    obv.iloc[i] = obv.iloc[i - 1] + volume.iloc[i]
                elif close.iloc[i] < close.iloc[i - 1]:
                    obv.iloc[i] = obv.iloc[i - 1] - volume.iloc[i]
                else:
                    obv.iloc[i] = obv.iloc[i - 1]

            return obv

        except Exception as e:
            self.logger.error(f"Error in manual OBV calculation: {e}")
            return pd.Series(index=close.index, data=0)

    def _calculate_trend_strength(self, series: pd.Series, periods: int = 20) -> float:
        """
        Calculate trend strength (-1 to 1, where 1 is strong uptrend).

        Args:
            series: Data series to analyze
            periods: Number of periods for analysis

        Returns:
            Trend strength value
        """
        try:
            if len(series) < periods:
                return 0.0

            # Linear regression slope over the period
            y = series.tail(periods).values
            x = np.arange(len(y))

            # Calculate slope
            slope = np.polyfit(x, y, 1)[0]

            # Normalize by the mean value to get relative strength
            mean_val = series.tail(periods).mean()
            if mean_val != 0:
                normalized_slope = slope / abs(mean_val)
            else:
                normalized_slope = 0

            # Clamp to [-1, 1] range
            return clamp(normalized_slope * 10)

        except Exception as e:
            self.logger.error(f"Error calculating trend strength: {e}")
            return 0.0

    def _calculate_obv_signal_strength(
        self, close: pd.Series, obv: pd.Series, volume: pd.Series
    ) -> float:
        """
        Calculate OBV signal strength (0-1).

        Args:
            close: Close price series
            obv: OBV series
            volume: Volume series

        Returns:
            Signal strength value
        """
        try:
            if len(close) < 20:
                return 0.5

            # Price momentum
            price_change = close.pct_change(periods=10).iloc[-1]

            # OBV momentum
            obv_change = obv.pct_change(periods=10).iloc[-1]

            # Volume consistency
            recent_volume = volume.tail(10)
            volume_consistency = 1.0 - (recent_volume.std() / recent_volume.mean())

            # Combine factors
            momentum_alignment = (
                1.0
                if (price_change > 0 and obv_change > 0) or (price_change < 0 and obv_change < 0)
                else 0.0
            )

            strength = (momentum_alignment * 0.6) + (volume_consistency * 0.4)

            return max(0.0, min(1.0, strength))

        except Exception as e:
            self.logger.error(f"Error calculating OBV signal strength: {e}")
            return 0.5

    def _interpret_obv_signals(
        self, obv: float, ma_short: float, ma_long: float, strength: float
    ) -> str:
        """
        Interpret OBV signals and trends.

        Args:
            obv: Current OBV value
            ma_short: Short-term OBV moving average
            ma_long: Long-term OBV moving average
            strength: Signal strength

        Returns:
            Interpretation string
        """
        if ma_short > ma_long and strength > 0.7:
            return "strong_bullish"
        elif ma_short > ma_long:
            return "bullish"
        elif ma_short < ma_long and strength > 0.7:
            return "strong_bearish"
        elif ma_short < ma_long:
            return "bearish"
        else:
            return "neutral"

    def calculate_accumulation_distribution(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """
        Calculate Accumulation/Distribution Line with enhanced analysis.

        Single implementation used by all modules.

        The A/D Line is a volume-based indicator that shows the relationship between
        price and volume to determine if a security is being accumulated or distributed.

        Features:
        - Standard A/D Line calculation
        - A/D Line trend analysis
        - Momentum and divergence detection
        - Signal strength scoring

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dictionary with A/D analysis or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=20):
            return None

        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            volume = df["volume"]

            # Calculate A/D Line
            if self.backend == "pandas_ta":
                ad_values = df.ta.ad(append=True)["AD"].values
            elif self.backend == "talib":
                ad_values = self.talib.AD(
                    high.astype(np.float64).values,
                    low.astype(np.float64).values,
                    close.astype(np.float64).values,
                    volume.astype(np.float64).values,
                )
            else:
                # Manual calculation
                ad_values = self._calculate_manual_ad_line(high, low, close, volume).values

            current_ad = self.core.safe_float_conversion(ad_values[-1], default=0.0)

            # A/D Line trend analysis
            ad_series = pd.Series(ad_values, index=df.index)
            ad_ma_10 = ad_series.rolling(window=10).mean()
            ad_ma_20 = ad_series.rolling(window=20).mean()

            current_ma_10 = self.core.safe_float_conversion(ad_ma_10.iloc[-1], default=current_ad)
            current_ma_20 = self.core.safe_float_conversion(ad_ma_20.iloc[-1], default=current_ad)

            # Signal strength and trend analysis
            signal_strength = self._calculate_ad_signal_strength(close, ad_series, volume)
            trend_strength = self._calculate_trend_strength(ad_series, periods=15)

            return {
                "ad_line": current_ad,
                "ad_ma_10": current_ma_10,
                "ad_ma_20": current_ma_20,
                "ad_trend": "accumulation" if current_ma_10 > current_ma_20 else "distribution",
                "trend_strength": trend_strength,
                "signal_strength": signal_strength,
                "ad_interpretation": self._interpret_ad_signals(
                    current_ad, current_ma_10, current_ma_20, trend_strength
                ),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "A/D Line")
            return None

    def _calculate_manual_ad_line(
        self, high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
    ) -> pd.Series:
        """
        Manual A/D Line calculation for fallback compatibility.

        Args:
            high: High price series
            low: Low price series
            close: Close price series
            volume: Volume series

        Returns:
            A/D Line series
        """
        try:
            # Money Flow Multiplier
            clv = ((close - low) - (high - close)) / (high - low)
            clv = clv.fillna(0)  # Handle cases where high == low

            # Money Flow Volume
            mfv = clv * volume

            # Accumulation/Distribution Line (cumulative sum)
            ad_line = mfv.cumsum()

            return ad_line

        except Exception as e:
            self.logger.error(f"Error in manual A/D calculation: {e}")
            return pd.Series(index=high.index, data=0)

    def _calculate_ad_signal_strength(
        self, close: pd.Series, ad_line: pd.Series, volume: pd.Series
    ) -> float:
        """
        Calculate A/D Line signal strength (0-1).

        Args:
            close: Close price series
            ad_line: A/D Line series
            volume: Volume series

        Returns:
            Signal strength value
        """
        try:
            if len(close) < 20:
                return 0.5

            # Recent trend alignment
            close_trend = close.tail(10).iloc[-1] - close.tail(10).iloc[0]
            ad_trend = ad_line.tail(10).iloc[-1] - ad_line.tail(10).iloc[0]

            # Check if trends align
            trend_alignment = (
                1.0
                if (close_trend > 0 and ad_trend > 0) or (close_trend < 0 and ad_trend < 0)
                else 0.0
            )

            # Volume magnitude
            recent_avg_volume = volume.tail(10).mean()
            historical_avg_volume = volume.tail(50).mean()
            volume_factor = (
                min(1.0, recent_avg_volume / historical_avg_volume)
                if historical_avg_volume > 0
                else 0.5
            )

            strength = (trend_alignment * 0.7) + (volume_factor * 0.3)

            return max(0.0, min(1.0, strength))

        except Exception as e:
            self.logger.error(f"Error calculating A/D signal strength: {e}")
            return 0.5

    def _interpret_ad_signals(self, ad: float, ma_10: float, ma_20: float, trend: float) -> str:
        """
        Interpret A/D Line signals.

        Args:
            ad: Current A/D Line value
            ma_10: 10-period A/D moving average
            ma_20: 20-period A/D moving average
            trend: Trend strength value

        Returns:
            Interpretation string
        """
        if ma_10 > ma_20 and trend > 0.3:
            return "Strong accumulation - institutional buying"
        elif ma_10 < ma_20 and trend < -0.3:
            return "Strong distribution - institutional selling"
        elif ma_10 > ma_20:
            return "Moderate accumulation - gradual buying"
        elif ma_10 < ma_20:
            return "Moderate distribution - gradual selling"
        else:
            return "Balanced accumulation/distribution"
