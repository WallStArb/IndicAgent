"""I7 Trend Following setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class TrendFollowingPlugin:
    """Trend-following setup: fires when regime = trending with structure confirmation.

    Reads I4 trend_regime, I3 swing_pattern/trend_strength, I6 ctf_score from frames["features"].
    Entry at current price, stop ATR-based, targets at 1R/2R/3R.
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
    regime_threshold: float = 0.5
    confidence_threshold: float = 0.4
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        # OPTIMIZATION (Phase 48): Check regime gate BEFORE expensive OHLCV extraction
        # TODO: Apply this pattern to remaining 34/36 I7 plugins (see mean_reversion.py for example)  # noqa: E501
        # Pattern: Check cheap regime gates (dict lookups) before expensive extract_ohlcv() (numpy conversion)  # noqa: E501
        # Estimated benefit: Skip ~144 numpy conversions per bar (80% early exit rate)
        trend_regime = features.get("trend_regime", 0.0)
        trend_conf = features.get("trend_confidence", 0.0)

        if abs(trend_regime) < self.regime_threshold or trend_conf < self.confidence_threshold:
            return no_signal()

        # Regime gate passed - now extract OHLCV (expensive numpy conversion)
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
        entry = price

        signal_type = signal_type_for_direction("trend", direction)
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        raw_conf = (
            0.45 * min(1.0, max(0.0, trend_conf))
            + 0.35 * min(1.0, max(0.0, abs(trend_strength)))
            + 0.20 * min(1.0, max(0.0, abs(swing_pattern)))
        )

        supporting = []
        if abs(trend_regime) >= 0.7:
            supporting.append("strong_trend_regime")
        if abs(ctf_score) >= 0.5:
            supporting.append("cross_timeframe_aligned")
        if abs(swing_pattern) >= 0.5:
            supporting.append("structure_confirmed")

        confidence = compose_confidence(raw_conf)
        if confidence < self.confidence_threshold:
            return no_signal()

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
