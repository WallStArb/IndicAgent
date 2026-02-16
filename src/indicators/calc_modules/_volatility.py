"""Volatility indicator calculations mixin (Bollinger Bands, ATR, Keltner Channels)."""

from typing import Any

import numpy as np
import pandas as pd


class VolatilityMixin:
    """Mixin providing volatility indicator calculations."""

    def calculate_bollinger_bands(
        self, df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
    ) -> dict[str, Any] | None:
        """
        Calculate Bollinger Bands.

        Single implementation used by all modules.

        Args:
            df: DataFrame with OHLCV data
            period: Moving average period (default 20)
            std_dev: Standard deviation multiplier (default 2.0)

        Returns:
            Dictionary with Bollinger Bands values or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=25):
            return None

        try:
            close = df["close"]

            if self.backend == "pandas_ta":
                # Use pandas-ta for Bollinger Bands
                bb_df = df.ta.bbands(length=period, std=std_dev)
                upper = bb_df[f"BBU_{period}_{std_dev}"].values
                middle = bb_df[f"BBM_{period}_{std_dev}"].values
                lower = bb_df[f"BBL_{period}_{std_dev}"].values
            elif self.backend == "talib":
                upper, middle, lower = self.talib.BBANDS(
                    close.values, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev, matype=0
                )
            else:  # finta
                bb_df = self.TA.BBANDS(df)
                upper = bb_df["BB_UPPER"].values
                middle = bb_df["BB_MIDDLE"].values
                lower = bb_df["BB_LOWER"].values

            # Calculate additional metrics
            current_price = close.iloc[-1]
            band_width = (upper[-1] - lower[-1]) / middle[-1] * 100 if middle[-1] != 0 else 0.0
            percent_b = (
                (current_price - lower[-1]) / (upper[-1] - lower[-1])
                if (upper[-1] - lower[-1]) != 0
                else 0.5
            )

            return {
                "upper": self.core.safe_float_conversion(upper[-1], default=0.0),
                "middle": self.core.safe_float_conversion(middle[-1], default=0.0),
                "lower": self.core.safe_float_conversion(lower[-1], default=0.0),
                "width": self.core.safe_float_conversion(band_width, default=0.0),
                "percent_b": self.core.safe_float_conversion(percent_b, default=0.5),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "Bollinger Bands")
            return None

    def calculate_bollinger_bands_series(
        self, df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate Bollinger Bands as full series.

        Args:
            df: DataFrame with OHLCV data
            period: Moving average period (default 20)
            std_dev: Standard deviation multiplier (default 2.0)

        Returns:
            Tuple of (upper_band, middle_band, lower_band) series
        """
        if not self.core.validate_dataframe(df, min_periods=25):
            return pd.Series(), pd.Series(), pd.Series()

        try:
            close = df["close"]

            if self.backend == "pandas_ta":
                # Use pandas-ta for Bollinger Bands
                bb_df = df.ta.bbands(length=period, std=std_dev)
                upper = bb_df[f"BBU_{period}_{std_dev}"]
                middle = bb_df[f"BBM_{period}_{std_dev}"]
                lower = bb_df[f"BBL_{period}_{std_dev}"]
            elif self.backend == "talib":
                upper_values, middle_values, lower_values = self.talib.BBANDS(
                    close.values, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev, matype=0
                )
                upper = pd.Series(upper_values, index=df.index)
                middle = pd.Series(middle_values, index=df.index)
                lower = pd.Series(lower_values, index=df.index)
            else:  # finta
                bb_df = self.TA.BBANDS(df)
                upper = bb_df["BB_UPPER"]
                middle = bb_df["BB_MIDDLE"]
                lower = bb_df["BB_LOWER"]

            return upper, middle, lower

        except Exception as e:
            self.core.handle_calculation_error(e, "Bollinger Bands Series")
            return pd.Series(), pd.Series(), pd.Series()

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> dict[str, Any] | None:
        """
        Calculate ATR (Average True Range) - Critical volatility indicator.

        Single implementation used by all modules.

        ATR measures market volatility and is essential for:
        - Stop-loss placement (2-3x ATR from entry)
        - Position sizing (risk per trade = account_risk / ATR)
        - Volatility-adjusted signals
        - Market regime classification

        Args:
            df: DataFrame with OHLCV data
            period: ATR period (default 14)

        Returns:
            Dictionary with ATR values or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=20):
            return None

        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]

            if self.backend == "pandas_ta":
                # Use pandas-ta for ATR
                atr_14 = df.ta.atr(length=14).values
                atr_10 = df.ta.atr(length=10).values
                atr_20 = df.ta.atr(length=20).values
            elif self.backend == "talib":
                # Standard ATR calculation (14-period default)
                atr_14 = self.talib.ATR(high.values, low.values, close.values, timeperiod=14)
                atr_10 = self.talib.ATR(high.values, low.values, close.values, timeperiod=10)
                atr_20 = self.talib.ATR(high.values, low.values, close.values, timeperiod=20)
            else:  # finta fallback
                # Manual ATR calculation
                atr_14 = self._calculate_manual_atr(df, period=14)
                atr_10 = self._calculate_manual_atr(df, period=10)
                atr_20 = self._calculate_manual_atr(df, period=20)

            # Current price for percentage calculations
            current_price = close.iloc[-1]

            # ATR as percentage of price (for comparing across different price levels)
            atr_14_pct = (atr_14[-1] / current_price * 100) if current_price > 0 else 0.0
            atr_10_pct = (atr_10[-1] / current_price * 100) if current_price > 0 else 0.0
            atr_20_pct = (atr_20[-1] / current_price * 100) if current_price > 0 else 0.0

            # Professional stop-loss levels (common futures trading multiples)
            stop_loss_1x = atr_14[-1] * 1.0  # Conservative stops
            stop_loss_2x = atr_14[-1] * 2.0  # Standard stops
            stop_loss_3x = atr_14[-1] * 3.0  # Wide stops for volatile markets

            # Professional profit targets (ATR-based)
            profit_target_1x = atr_14[-1] * 1.0  # 1:1 risk/reward
            profit_target_2x = atr_14[-1] * 2.0  # 1:2 risk/reward
            profit_target_3x = atr_14[-1] * 3.0  # 1:3 risk/reward

            # Volatility classification
            volatility_class = self._classify_volatility(atr_14_pct)

            # ATR trend analysis (rising/falling volatility)
            # Convert to pandas Series if it's a numpy array
            atr_14_series = (
                pd.Series(atr_14, index=df.index) if isinstance(atr_14, np.ndarray) else atr_14
            )
            atr_trend = self._analyze_atr_trend(atr_14_series)

            # Market regime classification based on ATR levels
            # Convert to pandas Series if they're numpy arrays
            atr_20_series = (
                pd.Series(atr_20, index=df.index) if isinstance(atr_20, np.ndarray) else atr_20
            )
            market_regime = self._classify_market_regime(atr_14_series, atr_20_series)

            # ATR expansion/contraction analysis
            atr_expansion = self._analyze_atr_expansion(atr_14_series)

            return {
                # Core ATR values (multiple timeframes for different trading styles)
                "atr_14": self.core.safe_float_conversion(atr_14[-1], default=0.0),
                "atr_10": self.core.safe_float_conversion(atr_10[-1], default=0.0),
                "atr_20": self.core.safe_float_conversion(atr_20[-1], default=0.0),
                # Percentage values (for cross-market comparison)
                "atr_14_pct": self.core.safe_float_conversion(atr_14_pct, default=0.0),
                "atr_10_pct": self.core.safe_float_conversion(atr_10_pct, default=0.0),
                "atr_20_pct": self.core.safe_float_conversion(atr_20_pct, default=0.0),
                # Professional stop-loss levels
                "stop_loss_1x": self.core.safe_float_conversion(stop_loss_1x, default=0.0),
                "stop_loss_2x": self.core.safe_float_conversion(stop_loss_2x, default=0.0),
                "stop_loss_3x": self.core.safe_float_conversion(stop_loss_3x, default=0.0),
                # Professional profit targets
                "profit_target_1x": self.core.safe_float_conversion(profit_target_1x, default=0.0),
                "profit_target_2x": self.core.safe_float_conversion(profit_target_2x, default=0.0),
                "profit_target_3x": self.core.safe_float_conversion(profit_target_3x, default=0.0),
                # Market analysis
                "volatility_class": volatility_class,
                "atr_trend": atr_trend,
                "market_regime": market_regime,
                "atr_expansion": atr_expansion,
                "current_price": self.core.safe_float_conversion(current_price, default=0.0),
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "ATR")
            return None

    def _calculate_manual_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Manual ATR calculation for finta fallback - OPTIMIZED with vectorization.

        ATR = Average of True Range over specified period
        True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        """
        # Use .values for faster NumPy operations
        high_vals = df["high"].values
        low_vals = df["low"].values
        close_vals = df["close"].values

        # OPTIMIZED: Vectorized True Range calculation
        prev_close = np.roll(close_vals, 1)
        prev_close[0] = close_vals[0]  # Handle first element

        tr1 = high_vals - low_vals
        tr2 = np.abs(high_vals - prev_close)
        tr3 = np.abs(low_vals - prev_close)

        # Vectorized maximum operation (much faster than pandas concat + max)
        true_range = np.maximum(tr1, np.maximum(tr2, tr3))

        # Calculate ATR using exponential moving average (more responsive than SMA)
        atr = pd.Series(true_range).ewm(span=period).mean()

        return atr

    def _classify_volatility(self, atr_pct: float) -> str:
        """
        Classify volatility based on ATR percentage of price.

        Args:
            atr_pct: ATR as percentage of current price

        Returns:
            Volatility classification
        """
        if atr_pct > 5.0:
            return "very_high"
        elif atr_pct > 3.0:
            return "high"
        elif atr_pct > 1.5:
            return "moderate"
        elif atr_pct > 0.5:
            return "low"
        else:
            return "very_low"

    def _analyze_atr_trend(self, atr_values: pd.Series) -> str:
        """
        Analyze ATR trend direction and strength.

        Args:
            atr_values: ATR values series

        Returns:
            ATR trend description
        """
        if len(atr_values) < 10:
            return "insufficient_data"

        recent_atr = atr_values[-10:].dropna()
        if len(recent_atr) < 5:
            return "insufficient_data"

        # Calculate trend slope
        slope = np.polyfit(range(len(recent_atr)), recent_atr, 1)[0]
        avg_atr = recent_atr.mean()

        # Normalize slope by average ATR for relative comparison
        relative_slope = slope / avg_atr if avg_atr > 0 else 0

        if relative_slope > 0.1:
            return "strong_expansion"
        elif relative_slope > 0.05:
            return "expansion"
        elif relative_slope > -0.05:
            return "stable"
        elif relative_slope > -0.1:
            return "contraction"
        else:
            return "strong_contraction"

    def _classify_market_regime(self, atr_14: pd.Series, atr_20: pd.Series) -> str:
        """
        Classify market regime based on ATR levels and trends.

        Args:
            atr_14: 14-period ATR series
            atr_20: 20-period ATR series

        Returns:
            Market regime classification
        """
        if len(atr_14) < 20 or len(atr_20) < 20:
            return "insufficient_data"

        current_atr_14 = atr_14.iloc[-1]
        current_atr_20 = atr_20.iloc[-1]

        # Calculate ATR ratio for regime classification
        atr_ratio = current_atr_14 / current_atr_20 if current_atr_20 > 0 else 1.0

        if atr_ratio > 1.2:
            return "volatility_expansion"
        elif atr_ratio < 0.8:
            return "volatility_contraction"
        elif current_atr_14 > atr_20.quantile(0.8):
            return "high_volatility"
        elif current_atr_14 < atr_20.quantile(0.2):
            return "low_volatility"
        else:
            return "normal_volatility"

    def _analyze_atr_expansion(self, atr_values: pd.Series) -> str:
        """
        Analyze ATR expansion/contraction patterns.

        Args:
            atr_values: ATR values series

        Returns:
            Expansion analysis
        """
        if len(atr_values) < 20:
            return "insufficient_data"

        # Calculate recent vs historical ATR
        recent_atr = atr_values[-5:].mean()
        historical_atr = atr_values[-20:].mean()

        if historical_atr == 0:
            return "insufficient_data"

        expansion_ratio = recent_atr / historical_atr

        if expansion_ratio > 1.5:
            return "strong_expansion"
        elif expansion_ratio > 1.2:
            return "moderate_expansion"
        elif expansion_ratio > 0.8:
            return "stable"
        elif expansion_ratio > 0.5:
            return "moderate_contraction"
        else:
            return "strong_contraction"

    def calculate_keltner_channels(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """
        Calculate Keltner Channels - ATR-based volatility bands.

        Single implementation used by all modules.

        Professional Keltner Channel implementation:
        - Middle Line: 20-period EMA (or SMA)
        - Upper Channel: Middle Line + (2.0 * ATR)
        - Lower Channel: Middle Line - (2.0 * ATR)

        Used for:
        - Trend identification (price above/below channels)
        - Breakout detection (price breaking channels)
        - Overbought/oversold conditions
        - Volatility-adjusted support/resistance

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dictionary with Keltner Channel values or None if calculation fails
        """
        if not self.core.validate_dataframe(df, min_periods=25):
            return None

        try:
            close = df["close"]
            high = df["high"]
            low = df["low"]

            # Calculate ATR (14-period for channel width)
            if self.backend == "talib":
                atr_14 = self.talib.ATR(high.values, low.values, close.values, timeperiod=14)
                # Use EMA for middle line (professional standard)
                middle_line = self.talib.EMA(close.values, timeperiod=20)
            else:
                # Manual calculation fallback
                atr_14 = self._calculate_manual_atr(df, period=14)
                middle_line = close.ewm(span=20).mean()
                atr_14 = atr_14.values
                middle_line = middle_line.values

            # Standard multiplier (2.0 is professional default, can be adjusted)
            multiplier = 2.0

            # Calculate channel lines
            upper_channel = middle_line + (multiplier * atr_14)
            lower_channel = middle_line - (multiplier * atr_14)

            # Current values
            current_price = self.core.safe_float_conversion(close.iloc[-1], default=0.0)
            current_upper = self.core.safe_float_conversion(upper_channel[-1], default=0.0)
            current_middle = self.core.safe_float_conversion(middle_line[-1], default=0.0)
            current_lower = self.core.safe_float_conversion(lower_channel[-1], default=0.0)

            # Channel width analysis
            channel_width = current_upper - current_lower
            channel_width_pct = (
                (channel_width / current_middle * 100) if current_middle > 0 else 0.0
            )

            # Price position within channels (similar to Bollinger %B)
            if channel_width > 0:
                price_position = (current_price - current_lower) / channel_width
            else:
                price_position = 0.5

            # Channel analysis
            keltner_condition = self._analyze_keltner_condition(
                current_price, current_upper, current_lower
            )

            # Convert to pandas Series if needed for trend analysis
            atr_series = (
                pd.Series(atr_14, index=df.index) if isinstance(atr_14, np.ndarray) else atr_14
            )

            keltner_trend = self._analyze_keltner_trend(close.values[-10:], middle_line[-10:])
            channel_squeeze = self._detect_channel_squeeze(atr_series, middle_line)
            breakout_potential = self._assess_breakout_potential(df, upper_channel, lower_channel)

            return {
                # Core Keltner values
                "upper_channel": current_upper,
                "middle_line": current_middle,
                "lower_channel": current_lower,
                # Channel metrics
                "channel_width": self.core.safe_float_conversion(channel_width, default=0.0),
                "channel_width_pct": self.core.safe_float_conversion(
                    channel_width_pct, default=0.0
                ),
                "price_position": self.core.safe_float_conversion(price_position, default=0.5),
                # Market analysis
                "keltner_condition": keltner_condition,
                "keltner_trend": keltner_trend,
                "channel_squeeze": channel_squeeze,
                "breakout_potential": breakout_potential,
                # Trading signals
                "above_upper": current_price > current_upper,
                "below_lower": current_price < current_lower,
                "inside_channels": current_lower <= current_price <= current_upper,
                # Additional metrics
                "current_price": current_price,
                "atr_multiplier": multiplier,
            }

        except Exception as e:
            self.core.handle_calculation_error(e, "Keltner Channels")
            return None

    def _analyze_keltner_condition(self, price: float, upper: float, lower: float) -> str:
        """
        Analyze current price position relative to Keltner Channels.

        Args:
            price: Current price
            upper: Upper channel line
            lower: Lower channel line

        Returns:
            Condition description
        """
        if price > upper:
            return "overbought"
        elif price < lower:
            return "oversold"
        elif price > (upper + lower) / 2:
            return "bullish_bias"
        else:
            return "bearish_bias"

    def _analyze_keltner_trend(self, prices: np.ndarray, middle_line: np.ndarray) -> str:
        """
        Analyze trend based on price action relative to Keltner middle line.

        Args:
            prices: Recent price values
            middle_line: Keltner middle line values

        Returns:
            Trend description
        """
        if len(prices) < 5 or len(middle_line) < 5:
            return "neutral"

        # Count periods where price is above/below middle line
        above_count = sum(1 for i in range(-5, 0) if prices[i] > middle_line[i])

        if above_count >= 4:
            return "bullish"
        elif above_count <= 1:
            return "bearish"
        else:
            return "neutral"

    def _detect_channel_squeeze(self, atr_values: pd.Series, middle_line: np.ndarray) -> bool:
        """
        Detect Keltner Channel squeeze (low volatility periods).

        Args:
            atr_values: ATR values series
            middle_line: Keltner middle line values

        Returns:
            True if squeeze detected
        """
        if len(atr_values) < 20:
            return False

        current_atr = atr_values.iloc[-1]
        recent_atr_avg = atr_values.iloc[-10:].mean()
        historical_atr_avg = atr_values.iloc[-20:].mean()

        # Squeeze detected when ATR is significantly below recent average
        return current_atr < historical_atr_avg * 0.8 and recent_atr_avg < historical_atr_avg * 0.85

    def _assess_breakout_potential(
        self, df: pd.DataFrame, upper: np.ndarray, lower: np.ndarray
    ) -> str:
        """
        Assess potential for breakout from Keltner Channels.

        Args:
            df: DataFrame with OHLCV data
            upper: Upper channel values
            lower: Lower channel values

        Returns:
            Breakout assessment
        """
        if len(df) < 10:
            return "insufficient_data"

        recent_highs = df["high"].iloc[-5:].values
        recent_lows = df["low"].iloc[-5:].values
        recent_upper = upper[-5:]
        recent_lower = lower[-5:]

        # Count touches of channel boundaries
        upper_touches = sum(1 for i in range(5) if recent_highs[i] >= recent_upper[i] * 0.999)
        lower_touches = sum(1 for i in range(5) if recent_lows[i] <= recent_lower[i] * 1.001)

        if upper_touches >= 2:
            return "upward_breakout_likely"
        elif lower_touches >= 2:
            return "downward_breakout_likely"
        else:
            return "consolidation"
