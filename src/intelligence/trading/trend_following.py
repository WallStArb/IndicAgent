"""I7 Trend Following setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import onset_guard
from .trade_framer import frame_trade

if TYPE_CHECKING:
    pass

_REGIME_MIN_DEFAULT: float = 0.5
_CONFIDENCE_MIN_DEFAULT: float = 0.4


@dataclass
class TrendFollowingPlugin:
    """Trend-following setup: fires once per trend confirmation onset.

    Reads I4 trend_regime, I3 swing_pattern/trend_strength, I6 ctf_score from frames["features"].
    Entry at current price, stop ATR-based, targets at 1R/2R/3R.

    onset_guard placed after ALL downstream gates — state commits only when signal emits.
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
    requires_i6_confluence: bool = True
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

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

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        # OPTIMIZATION (Phase 48): cheap regime gate before expensive OHLCV extraction.
        # onset_guard called here (before OHLCV) so it sees False when regime drops —
        # enabling proper rearm. swing_pattern checked post-OHLCV but is a dict lookup.
        trend_regime = features.get("trend_regime", 0.0)
        trend_conf = features.get("trend_confidence", 0.0)
        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        regime_condition = abs(trend_regime) >= regime_min and trend_conf >= confidence_min
        is_new_onset = onset_guard(self._state, state_key, regime_condition)
        if not regime_condition or not is_new_onset:
            return no_signal()

        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        swing_pattern = features.get("swing_pattern", 0.0)
        trend_strength = features.get("trend_strength", 0.0)
        ctf_score = features.get("ctf_score", 0.0)

        direction = 1 if trend_regime > 0 else -1
        if direction == 1 and swing_pattern <= 0:
            return no_signal()
        if direction == -1 and swing_pattern >= 0:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        price = float(close[-1])
        signal_type = signal_type_for_direction("trend", direction)
        tf = frame_trade(signal_type, direction, price, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        raw_conf = (
            0.45 * clamp01(trend_conf)
            + 0.35 * clamp01(abs(trend_strength))
            + 0.20 * clamp01(abs(swing_pattern))
        )
        confidence = compose_confidence(raw_conf)
        if confidence < confidence_min:
            return no_signal()

        supporting = []
        if abs(trend_regime) >= 0.7:
            supporting.append("strong_trend_regime")
        if abs(ctf_score) >= 0.5:
            supporting.append("cross_timeframe_aligned")
        if abs(swing_pattern) >= 0.5:
            supporting.append("structure_confirmed")

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
        )
        signal["features_snapshot"] = capture_signal_features(
            features, direction, "trend", signal["confidence"]
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = TrendFollowingPlugin()
