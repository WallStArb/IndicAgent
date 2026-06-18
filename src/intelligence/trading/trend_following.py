"""I7 Trend Following setup detection plugin.

Renaissance principle (Phase 124): fires on structural entries WITHIN a trend,
not on the trend state itself. Two structural triggers:

1. Pullback-to-MA reversal: price was below (bullish) or above (bearish) SMA
   for >= 5 bars, then crosses back in the trend direction.
2. Consolidation breakout: range compression < 0.5% for >= 5 bars, then close
   breaches the consolidation high (bullish) or low (bearish).

trend_regime is a context filter (must be trending), NOT the trigger.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import clamp01, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event
from .trade_framer import frame_trade

if TYPE_CHECKING:
    pass

_REGIME_MIN_DEFAULT: float = 0.5
_CONFIDENCE_MIN_DEFAULT: float = 0.4
_PULLBACK_MIN_BARS_DEFAULT: int = 5
_CONSOLIDATION_MIN_BARS_DEFAULT: int = 5
_CONSOLIDATION_RANGE_PCT_DEFAULT: float = 0.5


@dataclass
class TrendFollowingState:
    # below_sma_history[i] = True if close[i] was below SMA at bar i (for pullback detection)
    below_sma_history: deque = field(default_factory=lambda: deque(maxlen=50))
    consolidation_high: float | None = None
    consolidation_low: float | None = None
    consolidation_bars: int = 0


@dataclass
class TrendFollowingPlugin:
    """Trend-following setup: fires on structural entries within a trend.

    Reads I4 trend_regime/trend_confidence/trend_strength, I3 swing_pattern,
    I1 sma_20/ema_20, I6 ctf_score from frames["features"].

    Structural triggers (OR logic):
    - Pullback-to-MA reversal: close crosses back over SMA after >= 5 bars below (bullish)
      or crosses back under SMA after >= 5 bars above (bearish).
    - Consolidation breakout: range < 0.5% for >= 5 bars then close breaches range bound.

    Gate ordering: structural event first, trend_regime context filter second.
    """

    name: str = "trad_TrendFollowing"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "trend"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "trend"
    # Phase 126 IC audit: statistically anti-predictive on existing data
    # (IC=+0.023, hit_rate CI upper=0.250, n=2393 - all outcomes below 0.45 floor); redesign required.
    shadow_only: bool = True
    _state: dict[str, TrendFollowingState] = field(default_factory=dict)
    _dedup_state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def _get_state(self, symbol: str, tf: str) -> TrendFollowingState:
        key = f"{symbol}_{tf}"
        if key not in self._state:
            self._state[key] = TrendFollowingState()
        return self._state[key]

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        regime_min = (
            cfg.get_sync("threshold.trend_following.regime_min", _REGIME_MIN_DEFAULT)
            if cfg
            else _REGIME_MIN_DEFAULT
        )
        confidence_min = (
            cfg.get_sync("threshold.trend_following.confidence_min", _CONFIDENCE_MIN_DEFAULT)
            if cfg
            else _CONFIDENCE_MIN_DEFAULT
        )
        pullback_min_bars = int(
            cfg.get_sync("threshold.trend_following.pullback_min_bars", _PULLBACK_MIN_BARS_DEFAULT)
            if cfg
            else _PULLBACK_MIN_BARS_DEFAULT
        )
        consolidation_min_bars = int(
            cfg.get_sync(
                "threshold.trend_following.consolidation_min_bars", _CONSOLIDATION_MIN_BARS_DEFAULT
            )
            if cfg
            else _CONSOLIDATION_MIN_BARS_DEFAULT
        )
        consolidation_range_pct = float(
            cfg.get_sync(
                "threshold.trend_following.consolidation_range_pct",
                _CONSOLIDATION_RANGE_PCT_DEFAULT,
            )
            if cfg
            else _CONSOLIDATION_RANGE_PCT_DEFAULT
        )

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        state = self._get_state(symbol, tf_key)

        sma = features.get("sma_20") or features.get("ema_20")
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        price = float(close[-1])
        current_high = float(high[-1])
        current_low = float(low[-1])

        # Record whether this bar's close was below (or above) the SMA — stored as bool so
        # the pullback count compares the close vs. SMA at each historical bar, not SMA vs. today's close.
        if sma:
            current_sma_val = float(sma)
            state.below_sma_history.append(price < current_sma_val)

        trend_regime = features.get("trend_regime", 0.0)
        direction = 1 if trend_regime > 0 else -1

        # ── Structural event gate FIRST ──────────────────────────────────────
        pullback_reversal = False
        consolidation_breakout = False
        structural_type = "none"

        if sma and len(state.below_sma_history) >= pullback_min_bars:
            current_sma = float(sma)
            history = list(state.below_sma_history)
            # Prior N-1 bars: how many had close below SMA (bullish setup) or above (bearish)
            bars_below_sma = sum(1 for was_below in history[-pullback_min_bars:-1] if was_below)
            bars_above_sma = sum(1 for was_below in history[-pullback_min_bars:-1] if not was_below)

            if direction == 1 and bars_below_sma >= pullback_min_bars - 1 and price > current_sma:
                pullback_reversal = True
                structural_type = "pullback_reversal_bull"
            elif (
                direction == -1 and bars_above_sma >= pullback_min_bars - 1 and price < current_sma
            ):
                pullback_reversal = True
                structural_type = "pullback_reversal_bear"

        range_pct = (current_high - current_low) / price * 100 if price > 0 else 999.0
        if range_pct < consolidation_range_pct:
            state.consolidation_bars += 1
            state.consolidation_high = max(
                state.consolidation_high if state.consolidation_high is not None else current_high,
                current_high,
            )
            state.consolidation_low = min(
                state.consolidation_low if state.consolidation_low is not None else current_low,
                current_low,
            )
        else:
            # Check breakout against accumulated bounds before the reset clears them
            if (
                state.consolidation_bars >= consolidation_min_bars
                and state.consolidation_high is not None
                and state.consolidation_low is not None
            ):
                if direction == 1 and price > state.consolidation_high:
                    consolidation_breakout = True
                    structural_type = "consolidation_breakout_bull"
                elif direction == -1 and price < state.consolidation_low:
                    consolidation_breakout = True
                    structural_type = "consolidation_breakout_bear"

            state.consolidation_bars = 0
            state.consolidation_high = None
            state.consolidation_low = None

        if not pullback_reversal and not consolidation_breakout:
            return no_signal()

        # ── Context filter SECOND: trend_regime must be trending ─────────────
        trend_conf = features.get("trend_confidence", 0.0)
        if abs(trend_regime) < regime_min or trend_conf < confidence_min:
            return no_signal()

        # ── Context filter THIRD: swing_pattern alignment ─────────────────────
        swing_pattern = features.get("swing_pattern", 0.0)
        trend_strength = features.get("trend_strength", 0.0)
        ctf_score = features.get("ctf_score", 0.0)

        if direction == 1 and swing_pattern <= 0:
            return no_signal()
        if direction == -1 and swing_pattern >= 0:
            return no_signal()

        # ── FOURTH: Extract trade frame ───────────────────────────────────────
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        signal_type = signal_type_for_direction("trend", direction)
        tf = frame_trade(signal_type, direction, price, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # Wave B: factor audit trail - pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "trend_conf_score": round(clamp01(trend_conf), 4),
            "trend_strength_score": round(clamp01(abs(trend_strength)), 4),
            "swing_pattern_score": round(clamp01(abs(swing_pattern)), 4),
        }

        raw_conf = (
            0.45 * clamp01(trend_conf)
            + 0.35 * clamp01(abs(trend_strength))
            + 0.20 * clamp01(abs(swing_pattern))
        )
        confidence = compose_confidence(raw_conf)
        if confidence < confidence_min:
            return no_signal()

        # ── FIFTH: deduplicate_event prevents re-fire on same structural occurrence ──
        event_id = (direction, structural_type)
        if not deduplicate_event(self._dedup_state, state_key, event_id):
            return no_signal()

        supporting = []
        if abs(trend_regime) >= 0.7:
            supporting.append("strong_trend_regime")
        if abs(ctf_score) >= 0.5:
            supporting.append("cross_timeframe_aligned")
        if abs(swing_pattern) >= 0.5:
            supporting.append("structure_confirmed")
        supporting.append(structural_type)

        regime_ctx = "bullish" if direction == 1 else "bearish"
        signal = make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = TrendFollowingPlugin()
