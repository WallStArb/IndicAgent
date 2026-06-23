from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class VolatilityRegimePlugin:
    """Classify volatility regime from ATR percentile and BB width."""

    name: str = "ctx_VolatilityRegime"
    outputs: frozenset[str] = frozenset(
        {"vol_regime", "vol_percentile", "vol_expansion", "bb_width_pct", "bb_width_percentile"}
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    lookback: int = 50
    bb_period: int = 20
    atr_period: int = 14
    expansion_lag: int = 10
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        # ATR series: true range → rolling mean
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(
            high - low,
            np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
        )
        # Simple rolling mean ATR over atr_period
        atr_series = np.convolve(tr, np.ones(self.atr_period) / self.atr_period, mode="valid")

        if len(atr_series) < self.lookback:
            return {}

        window = atr_series[-self.lookback :]
        current_atr = atr_series[-1]

        # Percentile rank of current ATR in the lookback window
        vol_percentile = float(np.sum(window <= current_atr) / len(window))

        # Regime classification from percentile
        if vol_percentile < 0.20:
            vol_regime = -1.0  # LOW
        elif vol_percentile <= 0.80:
            vol_regime = 0.0  # NORMAL
        elif vol_percentile <= 0.95:
            vol_regime = 1.0  # HIGH
        else:
            vol_regime = 2.0  # EXTREME

        # BB width as % of mid price
        sma = np.convolve(close, np.ones(self.bb_period) / self.bb_period, mode="valid")
        if len(sma) < self.lookback:
            return {}
        # Per-window std: each element uses the exact same bb_period bars as its SMA.
        # STREAMING ONLY — this comprehension is O(n * bb_period) per call, safe when the
        # close array is bounded by the live pipeline's window. If this ever enters a batch
        # loop over n bars (growing series) it becomes O(n²). Use a vectorized rolling-std
        # (e.g. pandas rolling or stride-trick) if a batch path is needed.
        bb_std = np.array([np.std(close[i : i + self.bb_period]) for i in range(len(sma))])
        bb_upper = sma + 2 * bb_std
        bb_lower = sma - 2 * bb_std
        bb_mid = sma
        bb_width = (bb_upper - bb_lower) / np.where(bb_mid != 0, bb_mid, 1.0)

        bb_width_pct = float(bb_width[-1])
        # Percentile of current BB width
        bw_window = bb_width[-self.lookback :] if len(bb_width) >= self.lookback else bb_width
        bb_width_percentile = float(np.sum(bw_window <= bb_width_pct) / len(bw_window))

        # Expansion / contraction: continuous ratio deviation from 1.0
        # Positive = expanding volatility, negative = contracting
        if len(atr_series) > self.expansion_lag:
            lagged_atr = atr_series[-(self.expansion_lag + 1)]
            ratio = current_atr / lagged_atr if lagged_atr > 0 else 1.0
            vol_expansion = ratio - 1.0  # continuous: 0 = stable, >0 = expanding, <0 = contracting
        else:
            vol_expansion = 0.0

        return {
            "vol_regime": vol_regime,
            "vol_percentile": round(vol_percentile, 4),
            "vol_expansion": vol_expansion,
            "bb_width_pct": round(bb_width_pct, 4),
            "bb_width_percentile": round(bb_width_percentile, 4),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VolatilityRegimePlugin()
