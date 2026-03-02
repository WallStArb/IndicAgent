from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec


@dataclass
class CandlestickPatternsPlugin:
    """Single and two-bar candlestick pattern detection."""

    name: str = "patt_CandlestickPatterns"
    outputs: set[str] = frozenset(
        {
            "engulfing_bull",
            "engulfing_bear",
            "pin_bar_bull",
            "pin_bar_bear",
            "hammer_detected",
            "shooting_star_detected",
            "inside_bar",
            "outside_bar",
            "doji_detected",
        }
    )
    min_lookback: int = 2
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"pattern"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features") or {}

        # Current and prior bars
        c = df.iloc[-1]
        p = df.iloc[-2]

        c_o, c_h, c_l, c_c = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        p_o, p_h, p_l, p_c = float(p["open"]), float(p["high"]), float(p["low"]), float(p["close"])

        # Current bar metrics
        c_range = c_h - c_l
        c_body = abs(c_c - c_o)
        c_upper_wick = c_h - max(c_o, c_c)
        c_lower_wick = min(c_o, c_c) - c_l
        c_bullish = c_c > c_o
        c_bearish = c_c < c_o

        # Prior bar metrics
        p_bullish = p_c > p_o
        p_bearish = p_c < p_o

        # Body top/bottom for engulfing
        c_body_top = max(c_o, c_c)
        c_body_bot = min(c_o, c_c)
        p_body_top = max(p_o, p_c)
        p_body_bot = min(p_o, p_c)

        # Engulfing bull: current bullish, prior bearish, current engulfs prior
        engulfing_bull = 0.0
        if c_bullish and p_bearish and c_body_bot <= p_body_bot and c_body_top >= p_body_top:
            engulfing_bull = 1.0

        # Engulfing bear: current bearish, prior bullish, current engulfs prior
        engulfing_bear = 0.0
        if c_bearish and p_bullish and c_body_bot <= p_body_bot and c_body_top >= p_body_top:
            engulfing_bear = 1.0

        # Pin bar bull: long lower wick, small body + upper wick
        pin_bar_bull = 0.0
        if c_body > 0 and c_lower_wick >= 2.0 * c_body and c_upper_wick <= c_body:
            pin_bar_bull = 1.0

        # Pin bar bear: long upper wick, small body + lower wick
        pin_bar_bear = 0.0
        if c_body > 0 and c_upper_wick >= 2.0 * c_body and c_lower_wick <= c_body:
            pin_bar_bear = 1.0

        # Hammer: pin bar bull near support
        hammer_detected = 0.0
        if pin_bar_bull == 1.0:
            nearest_support = features.get("nearest_support")
            if isinstance(nearest_support, (int, float)) and nearest_support > 0:
                dist_pct = abs(c_c - nearest_support) / nearest_support
                if dist_pct < 0.005:  # within 0.5% of support
                    hammer_detected = 1.0
            else:
                # No support info → treat any pin bar bull as potential hammer
                hammer_detected = 1.0

        # Shooting star: pin bar bear near resistance
        shooting_star_detected = 0.0
        if pin_bar_bear == 1.0:
            nearest_resistance = features.get("nearest_resistance")
            if isinstance(nearest_resistance, (int, float)) and nearest_resistance > 0:
                dist_pct = abs(c_c - nearest_resistance) / nearest_resistance
                if dist_pct < 0.005:
                    shooting_star_detected = 1.0
            else:
                shooting_star_detected = 1.0

        # Inside bar: current bar inside prior bar
        inside_bar = 1.0 if (c_h < p_h and c_l > p_l) else 0.0

        # Outside bar: current bar engulfs prior bar (high and low)
        outside_bar = 1.0 if (c_h > p_h and c_l < p_l) else 0.0

        # Doji: body < 10% of range
        doji_detected = 0.0
        if c_range > 0 and c_body / c_range < 0.10:
            doji_detected = 1.0

        return {
            "engulfing_bull": engulfing_bull,
            "engulfing_bear": engulfing_bear,
            "pin_bar_bull": pin_bar_bull,
            "pin_bar_bear": pin_bar_bear,
            "hammer_detected": hammer_detected,
            "shooting_star_detected": shooting_star_detected,
            "inside_bar": inside_bar,
            "outside_bar": outside_bar,
            "doji_detected": doji_detected,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CandlestickPatternsPlugin()
