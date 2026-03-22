"""I7 Momentum Breakout setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import extract_ohlcv, no_signal


@dataclass
class MomentumBreakoutPlugin:
    """Momentum breakout setup: fires on ROC spike + volume expansion + structure break.

    All three gates are required (triple-gate sequential). Any failure → no signal.
    ROC direction must match structure break direction.
    Stop is placed at the broken structure level (new S/R), not from entry price.
    """

    name: str = "trad_MomentumBreakout"
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
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "breakout", "momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "trend"
    roc_period: int = 14
    roc_threshold: float = 0.3
    volume_expansion_threshold: float = 1.5
    atr_stop_multiplier: float = 1.0
    atr_target_multipliers: tuple = (1.5, 3.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

        df = frames.get("main")
        volume = df["volume"].to_numpy(dtype=float)
        price = float(close[-1])

        # ── Gate A: ROC spike ──
        # Use pipeline feature if available (ROC_PPO in I1_PLUGINS), else compute inline
        roc = features.get(f"roc_{self.roc_period}")
        if roc is None:
            if len(close) > self.roc_period:
                past = float(close[-1 - self.roc_period])
                roc = (price - past) / past * 100.0 if past != 0 else 0.0
            else:
                return no_signal()

        if abs(roc) <= self.roc_threshold:
            return no_signal()

        # ── Gate B: volume expansion ──
        vol_sma = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
        if vol_sma <= 0:
            return no_signal()
        volume_ratio = float(volume[-1]) / vol_sma
        if volume_ratio <= self.volume_expansion_threshold:
            return no_signal()

        # ── Gate C + direction: structure break must match ROC direction ──
        swing_high = features.get("swing_high", 0.0)
        swing_low = features.get("swing_low", 0.0)

        if roc > 0:
            if swing_high <= 0 or price <= swing_high:
                return no_signal()
            direction = 1
            structure_level = float(swing_high)
        else:
            if swing_low <= 0 or price >= swing_low:
                return no_signal()
            direction = -1
            structure_level = float(swing_low)

        # ── ATR ──
        atr = get_atr(features)
        if atr is None:
            return no_signal()

        entry = price

        # Stop at broken structure level (now acts as S/R)
        if direction == 1:
            stop = structure_level - atr * self.atr_stop_multiplier
        else:
            stop = structure_level + atr * self.atr_stop_multiplier

        # Targets
        targets = [
            round(entry + atr * m, 2) if direction == 1 else round(entry - atr * m, 2)
            for m in self.atr_target_multipliers
        ]

        # ── Confidence ──
        roc_score = min(1.0, (abs(roc) - self.roc_threshold) / self.roc_threshold)
        vol_score = min(
            1.0,
            (volume_ratio - self.volume_expansion_threshold) / self.volume_expansion_threshold,
        )
        break_margin = min(1.0, max(0.0, abs(price - structure_level) / atr))

        trend_regime = features.get("trend_regime", 0.0)
        regime_aligns = (direction == 1 and trend_regime > 0) or (
            direction == -1 and trend_regime < 0
        )
        if abs(trend_regime) < 0.3:
            regime_score = 0.5
        elif regime_aligns:
            regime_score = 1.0
        else:
            regime_score = 0.1

        raw_conf = 0.35 * roc_score + 0.30 * vol_score + 0.20 * break_margin + 0.15 * regime_score

        # Supporting factors
        supporting = [
            f"roc_spike_{abs(roc):.1f}pct",
            f"volume_{volume_ratio:.1f}x_expansion",
            "structure_break_long" if direction == 1 else "structure_break_short",
        ]
        if regime_aligns and abs(trend_regime) >= 0.3:
            supporting.append("trend_regime_aligned")

        # Zone friction penalty
        in_supply = float(features.get("in_supply_zone", 0.0))
        in_demand = float(features.get("in_demand_zone", 0.0))
        supply_str = float(features.get("supply_strength", 0.0))
        demand_str = float(features.get("demand_strength", 0.0))
        if direction == 1 and in_supply == 1.0:
            raw_conf -= 0.12 * supply_str
            supporting.append("penalty_supply_zone_friction")
        elif direction == -1 and in_demand == 1.0:
            raw_conf -= 0.12 * demand_str
            supporting.append("penalty_demand_zone_friction")
        raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        signal_type = "momentum_breakout_long" if direction == 1 else "momentum_breakout_short"
        regime_ctx = "breakout_bullish" if direction == 1 else "breakout_bearish"

        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_signal_features(
            features, direction, "trend", signal["confidence"]
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MomentumBreakoutPlugin()
