"""I7 VWAP Deviation setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec

_VOL_THRESHOLDS: dict[int, float] = {0: 2.0, 1: 2.0, 2: 2.5, 3: 3.0}


@dataclass
class VWAPDeviationPlugin:
    """VWAP Deviation setup: fires when price extends >2σ from session VWAP.

    Reads vwap, vwap_upper_2, vwap_lower_2, vwap_std from I1 VWAP plugin.
    Long when price < vwap_lower_2, short when price > vwap_upper_2.
    Targets: T1 = VWAP (the mean), T2 = opposite 1σ band.
    Confidence: deviation magnitude, regime compatibility, volume contraction.
    """

    name: str = "trad_VWAPDeviation"
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "vwap", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    sigma_threshold: float = 2.0
    atr_stop_multiplier: float = 1.5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        # ── VWAP features ──
        vwap = features.get("vwap", 0.0)
        vwap_std = features.get("vwap_std", 0.0)
        vwap_upper_1 = features.get("vwap_upper_1", 0.0)
        vwap_lower_1 = features.get("vwap_lower_1", 0.0)

        # Gate: VWAP must be meaningful (session has volume)
        if vwap_std <= 0 or vwap <= 0:
            return self._no_signal()

        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        price = float(close[-1])

        # Gate: price must be outside dynamic sigma threshold (GARCH-adaptive)
        vol_regime = int(features.get("garch_vol_regime", 1))
        effective_threshold = _VOL_THRESHOLDS.get(vol_regime, 2.0)
        sigma_deviation = abs(price - vwap) / vwap_std
        if sigma_deviation < effective_threshold:
            return self._no_signal()

        # Direction
        direction = 1 if price < vwap else -1

        # ATR
        atr = features.get("atr_14", 0.0)
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = price

        # Stop loss
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
        else:
            stop = entry + atr * self.atr_stop_multiplier

        # Targets: T1 = vwap, T2 = opposite 1σ band
        if direction == 1:
            t2 = vwap_upper_1 if vwap_upper_1 > 0 else vwap + vwap_std
        else:
            t2 = vwap_lower_1 if vwap_lower_1 > 0 else vwap - vwap_std
        targets = [round(float(vwap), 2), round(float(t2), 2)]

        # ── Confidence ──

        # Deviation score (0.40): sigma excess beyond 2σ, capped at 4σ
        sigma_deviation = abs(price - vwap) / vwap_std
        dev_score = min(1.0, max(0.0, (sigma_deviation - 2.0) / 2.0))

        # Regime compatibility (0.35): trend_regime aligned with reversion direction
        trend_regime = features.get("trend_regime", 0.0)
        regime_aligns = (direction == 1 and trend_regime > 0) or (
            direction == -1 and trend_regime < 0
        )
        if abs(trend_regime) < 0.3:
            regime_compat = 0.50
        elif regime_aligns:
            regime_compat = 0.70 + 0.30 * abs(trend_regime)
        else:
            regime_compat = max(0.0, 0.50 - abs(trend_regime))

        # Volume contraction (0.25): lower volume = better fade
        vol_sma = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
        volume_ratio = float(volume[-1]) / vol_sma if vol_sma > 0 else 1.0
        vol_contraction = max(0.0, 1.0 - max(0.0, volume_ratio - 1.0))

        raw_conf = 0.40 * dev_score + 0.35 * regime_compat + 0.25 * vol_contraction
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # Supporting factors
        supporting = ["vwap_2sigma_breach", f"vwap_{sigma_deviation:.1f}sigma_deviation"]
        if abs(trend_regime) < 0.3:
            supporting.append("ranging_regime")
        if volume_ratio < 1.0:
            supporting.append("low_volume_deviation")
        if regime_aligns and abs(trend_regime) >= 0.3:
            supporting.append("regime_aligned")

        signal_type = "vwap_reversion_long" if direction == 1 else "vwap_reversion_short"
        regime_ctx = "vwap_extended_low" if direction == 1 else "vwap_extended_high"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = VWAPDeviationPlugin()
