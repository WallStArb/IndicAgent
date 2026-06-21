from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.trading.atr_utils import get_atr


@dataclass
class CandlestickPatternsPlugin:
    """Single, two-bar, and three-bar candlestick pattern detection."""

    name: str = "patt_CandlestickPatterns"
    outputs: frozenset[str] = frozenset(
        {
            # --- Existing 9 outputs (unchanged) ---
            "engulfing_bull",
            "engulfing_bear",
            "pin_bar_bull",
            "pin_bar_bear",
            "hammer_detected",
            "shooting_star_detected",
            "inside_bar",
            "outside_bar",
            "doji_detected",
            # --- 10 new Tier 1 three-bar outputs ---
            "three_white_soldiers",
            "three_black_crows",
            "morning_star",
            "evening_star",
            "three_inside_up",
            "three_inside_down",
            "harami_cross",
            "dark_cloud_cover",
            "piercing_line",
            # --- 10 new Phase 42 patterns ---
            "harami_bull",
            "harami_bear",
            "abandoned_baby_bull",
            "abandoned_baby_bear",
            "tweezer_top",
            "tweezer_bottom",
            "belt_hold_bull",
            "belt_hold_bear",
            "kicker_bull",
            "kicker_bear",
            # --- Gradient companions ---
            "inside_bar_depth",
            "outside_bar_expansion",
        }
    )
    min_lookback: int = 3
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }

        # Current, prior, and two-bars-ago
        c = df.iloc[-1]
        p = df.iloc[-2]
        pp = df.iloc[-3]

        c_o, c_h, c_l, c_c = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        p_o, p_h, p_l, p_c = float(p["open"]), float(p["high"]), float(p["low"]), float(p["close"])
        pp_o = float(pp["open"])
        pp_h = float(pp["high"])
        pp_l = float(pp["low"])
        pp_c = float(pp["close"])

        # ------------------------------------------------------------------ #
        # Current bar metrics
        # ------------------------------------------------------------------ #
        c_range = c_h - c_l
        c_body = abs(c_c - c_o)
        c_upper_wick = c_h - max(c_o, c_c)
        c_lower_wick = min(c_o, c_c) - c_l
        c_bullish = c_c > c_o
        c_bearish = c_c < c_o

        # Prior bar metrics
        p_range = p_h - p_l
        p_body = abs(p_c - p_o)
        p_bullish = p_c > p_o
        p_bearish = p_c < p_o

        # Two-bars-ago metrics
        pp_range = pp_h - pp_l
        pp_body = abs(pp_c - pp_o)
        pp_bullish = pp_c > pp_o
        pp_bearish = pp_c < pp_o

        # Body top/bottom for engulfing
        c_body_top = max(c_o, c_c)
        c_body_bot = min(c_o, c_c)
        p_body_top = max(p_o, p_c)
        p_body_bot = min(p_o, p_c)

        # ------------------------------------------------------------------ #
        # Existing 9 patterns — unchanged logic
        # ------------------------------------------------------------------ #

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

        # Inside bar depth: how deeply contained within prior bar
        inside_bar_depth = 0.0
        if inside_bar == 1.0 and p_range > 0:
            margin_top = p_h - c_h
            margin_bot = c_l - p_l
            inside_bar_depth = min(margin_top, margin_bot) / p_range
            inside_bar_depth = max(0.0, min(1.0, inside_bar_depth))

        # Outside bar: current bar engulfs prior bar (high and low)
        outside_bar = 1.0 if (c_h > p_h and c_l < p_l) else 0.0

        # Outside bar expansion: total expansion relative to prior range
        outside_bar_expansion = 0.0
        if outside_bar == 1.0 and p_range > 0:
            expansion_top = c_h - p_h
            expansion_bot = p_l - c_l
            outside_bar_expansion = min(3.0, (expansion_top + expansion_bot) / p_range)

        # Doji: body < 10% of range
        doji_detected = 0.0
        if c_range > 0 and c_body / c_range < 0.10:
            doji_detected = 1.0

        # ------------------------------------------------------------------ #
        # 10 new Tier 1 three-bar patterns
        # ------------------------------------------------------------------ #

        # --- Three White Soldiers (bullish) ---
        # 3 consecutive bullish bars; each opens within prior body; each closes near high
        three_white_soldiers = 0.0
        if (
            pp_bullish
            and p_bullish
            and c_bullish
            # Each body > 0.5 * range (strong bars, not dojis)
            and pp_range > 0
            and pp_body > 0.5 * pp_range
            and p_range > 0
            and p_body > 0.5 * p_range
            and c_range > 0
            and c_body > 0.5 * c_range
            # p opens within pp body
            and p_o > min(pp_o, pp_c)
            and p_o < max(pp_o, pp_c)
            # c opens within p body
            and c_o > min(p_o, p_c)
            and c_o < max(p_o, p_c)
            # Each upper wick < 0.25 * body (closes near high)
            and (pp_h - pp_c) < 0.25 * pp_body
            and (p_h - p_c) < 0.25 * p_body
            and (c_h - c_c) < 0.25 * c_body
        ):
            three_white_soldiers = 1.0

        # --- Three Black Crows (bearish) --- mirror of Three White Soldiers
        three_black_crows = 0.0
        if (
            pp_bearish
            and p_bearish
            and c_bearish
            # Each body > 0.5 * range
            and pp_range > 0
            and pp_body > 0.5 * pp_range
            and p_range > 0
            and p_body > 0.5 * p_range
            and c_range > 0
            and c_body > 0.5 * c_range
            # p opens within pp body (between pp_c and pp_o, bearish so pp_c < pp_o)
            and p_o < max(pp_o, pp_c)
            and p_o > min(pp_o, pp_c)
            # c opens within p body
            and c_o < max(p_o, p_c)
            and c_o > min(p_o, p_c)
            # Each lower wick < 0.25 * body (closes near low)
            and (pp_c - pp_l) < 0.25 * pp_body
            and (p_c - p_l) < 0.25 * p_body
            and (c_c - c_l) < 0.25 * c_body
        ):
            three_black_crows = 1.0

        # --- Morning Star (bullish reversal) ---
        # pp = large bearish; p = small body (star/indecision); c = large bullish above pp midpoint
        morning_star = 0.0
        if (
            pp_bearish
            and pp_range > 0
            and pp_body > 0.6 * pp_range
            and p_range > 0
            and p_body < 0.3 * p_range
            and c_bullish
            and c_range > 0
            and c_body > 0.6 * c_range
            and c_c > (pp_o + pp_c) / 2.0
        ):
            morning_star = 1.0

        # --- Evening Star (bearish reversal) --- mirror of Morning Star
        # pp = large bullish; p = small body (star/indecision); c = large bearish below pp midpoint
        evening_star = 0.0
        if (
            pp_bullish
            and pp_range > 0
            and pp_body > 0.6 * pp_range
            and p_range > 0
            and p_body < 0.3 * p_range
            and c_bearish
            and c_range > 0
            and c_body > 0.6 * c_range
            and c_c < (pp_o + pp_c) / 2.0
        ):
            evening_star = 1.0

        # --- Three Inside Up (bullish continuation of reversal) ---
        # pp = large bearish; p = bullish harami inside pp; c = bullish close above pp_o
        three_inside_up = 0.0
        if (
            pp_bearish
            and pp_range > 0
            and pp_body > 0.5 * pp_range
            # p is bullish harami: opens above pp_c, closes below pp_o, and closes higher than opens
            and p_o > pp_c
            and p_c < pp_o
            and p_bullish
            # c is bullish and closes above pp_o (full reversal confirmed)
            and c_bullish
            and c_c > pp_o
        ):
            three_inside_up = 1.0

        # --- Three Inside Down (bearish) --- mirror of Three Inside Up
        # pp = large bullish; p = bearish harami inside pp; c = bearish close below pp_o
        three_inside_down = 0.0
        if (
            pp_bullish
            and pp_range > 0
            and pp_body > 0.5 * pp_range
            # p is bearish harami: opens below pp_c, closes above pp_o, and closes lower than opens
            and p_o < pp_c
            and p_c > pp_o
            and p_bearish
            # c is bearish and closes below pp_o
            and c_bearish
            and c_c < pp_o
        ):
            three_inside_down = 1.0

        # --- Harami Cross (reversal signal) ---
        # pp = large body (either direction); p = doji entirely inside pp body
        harami_cross = 0.0
        pp_body_high = max(pp_o, pp_c)
        pp_body_low = min(pp_o, pp_c)
        p_doji_body = abs(p_c - p_o)
        if (
            pp_range > 0
            and pp_body > 0.6 * pp_range
            and p_range > 0
            and p_doji_body / p_range < 0.10
            and p_h <= pp_body_high
            and p_l >= pp_body_low
        ):
            harami_cross = 1.0

        # --- Dark Cloud Cover (bearish) ---
        # pp = bullish; c opens above pp_high; c closes below pp midpoint but above pp_open
        dark_cloud_cover = 0.0
        if pp_bullish and c_o > pp_h and c_c < (pp_o + pp_c) / 2.0 and c_c > pp_o:
            dark_cloud_cover = 1.0

        # --- Piercing Line (bullish) ---
        # pp = bearish; c opens below pp_low; c closes above pp midpoint but below pp_open
        piercing_line = 0.0
        if pp_bearish and c_o < pp_l and c_c > (pp_o + pp_c) / 2.0 and c_c < pp_o:
            piercing_line = 1.0

        # ------------------------------------------------------------------ #
        # 10 new Phase 42 patterns
        # ------------------------------------------------------------------ #

        # --- Harami Bull (directional variant - p is bullish harami inside pp) ---
        harami_bull = 0.0
        if (
            pp_range > 0
            and pp_body > 0.5 * pp_range
            and p_range > 0
            and p_body < 0.3 * p_range
            and p_h <= pp_body_high
            and p_l >= pp_body_low
            and p_bullish
        ):
            harami_bull = 1.0

        # --- Harami Bear (directional variant - p is bearish harami inside pp) ---
        harami_bear = 0.0
        if (
            pp_range > 0
            and pp_body > 0.5 * pp_range
            and p_range > 0
            and p_body < 0.3 * p_range
            and p_h <= pp_body_high
            and p_l >= pp_body_low
            and p_bearish
        ):
            harami_bear = 1.0

        # --- Abandoned Baby Bull (gap up doji + bullish reversal) ---
        abandoned_baby_bull = 0.0
        gap_up = p_l > pp_h  # gap up: p low above pp high
        if (
            pp_bearish
            and pp_range > 0
            and pp_body > 0.6 * pp_range
            and gap_up
            and p_range > 0
            and p_body / p_range < 0.10  # doji
            and c_bullish
            and c_range > 0
            and c_body > 0.6 * c_range
        ):
            abandoned_baby_bull = 1.0

        # --- Abandoned Baby Bear (gap down doji + bearish reversal) ---
        abandoned_baby_bear = 0.0
        gap_down = p_h < pp_l  # gap down: p high below pp low
        if (
            pp_bullish
            and pp_range > 0
            and pp_body > 0.6 * pp_range
            and gap_down
            and p_range > 0
            and p_body / p_range < 0.10
            and c_bearish
            and c_range > 0
            and c_body > 0.6 * c_range
        ):
            abandoned_baby_bear = 1.0

        # --- Tweezer Top (near-identical highs between p and c) ---
        tweezer_top = 0.0
        atr_val = get_atr(features) or 0.0
        if atr_val > 0 and abs(p_h - c_h) <= 0.1 * atr_val:
            tweezer_top = 1.0

        # --- Tweezer Bottom (near-identical lows between p and c) ---
        tweezer_bottom = 0.0
        if atr_val > 0 and abs(p_l - c_l) <= 0.1 * atr_val:
            tweezer_bottom = 1.0

        # --- Belt Hold Bull (long white candle, no upper wick) ---
        belt_hold_bull = 0.0
        if c_bullish and c_range > 0 and c_body > 0.70 * c_range and c_upper_wick < 0.10 * c_range:
            belt_hold_bull = 1.0

        # --- Belt Hold Bear (long black candle, no lower wick) ---
        belt_hold_bear = 0.0
        if c_bearish and c_range > 0 and c_body > 0.70 * c_range and c_lower_wick < 0.10 * c_range:
            belt_hold_bear = 1.0

        # --- Kicker Bull (3-bar: pp bearish, c gaps above pp_h, c bullish large body) ---
        kicker_bull = 0.0
        gap_up_clean = pp_bearish and c_o > pp_h
        if (
            gap_up_clean
            and c_bullish
            and c_range > 0
            and c_body > 0.6 * c_range
            and c_upper_wick < 0.15 * c_range
        ):
            kicker_bull = 1.0

        # --- Kicker Bear (3-bar: pp bullish, c gaps below pp_l, c bearish large body) ---
        kicker_bear = 0.0
        gap_down_clean = pp_bullish and c_o < pp_l
        if (
            gap_down_clean
            and c_bearish
            and c_range > 0
            and c_body > 0.6 * c_range
            and c_lower_wick < 0.15 * c_range
        ):
            kicker_bear = 1.0

        return {
            # Existing 9
            "engulfing_bull": engulfing_bull,
            "engulfing_bear": engulfing_bear,
            "pin_bar_bull": pin_bar_bull,
            "pin_bar_bear": pin_bar_bear,
            "hammer_detected": hammer_detected,
            "shooting_star_detected": shooting_star_detected,
            "inside_bar": inside_bar,
            "outside_bar": outside_bar,
            "inside_bar_depth": round(inside_bar_depth, 4),
            "outside_bar_expansion": round(outside_bar_expansion, 4),
            "doji_detected": doji_detected,
            # 10 new Tier 1 three-bar patterns
            "three_white_soldiers": three_white_soldiers,
            "three_black_crows": three_black_crows,
            "morning_star": morning_star,
            "evening_star": evening_star,
            "three_inside_up": three_inside_up,
            "three_inside_down": three_inside_down,
            "harami_cross": harami_cross,
            "dark_cloud_cover": dark_cloud_cover,
            "piercing_line": piercing_line,
            # 10 new Phase 42 patterns
            "harami_bull": harami_bull,
            "harami_bear": harami_bear,
            "abandoned_baby_bull": abandoned_baby_bull,
            "abandoned_baby_bear": abandoned_baby_bear,
            "tweezer_top": tweezer_top,
            "tweezer_bottom": tweezer_bottom,
            "belt_hold_bull": belt_hold_bull,
            "belt_hold_bear": belt_hold_bear,
            "kicker_bull": kicker_bull,
            "kicker_bear": kicker_bear,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CandlestickPatternsPlugin()
