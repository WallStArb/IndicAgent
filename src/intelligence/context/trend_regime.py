from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class TrendRegimePlugin:
    """Classify trend regime from MA alignment and optional I3 structure blending."""

    name: str = "ctx_TrendRegime"
    outputs: set[str] = frozenset(
        {"trend_regime", "trend_confidence", "ma_alignment", "price_vs_sma20_pct"}
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"context"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    sma_fast: int = 20
    sma_slow: int = 50
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        # Compute SMAs from OHLCV
        sma20 = float(np.mean(close[-self.sma_fast :]))
        sma50 = float(np.mean(close[-self.sma_slow :]))
        price = float(close[-1])

        # MA alignment scoring
        if price > sma20 > sma50:
            ma_signal = 2.0  # Strong bullish
        elif price > sma20:
            ma_signal = 1.0  # Weak bullish
        elif price < sma20 < sma50:
            ma_signal = -2.0  # Strong bearish
        elif price < sma20:
            ma_signal = -1.0  # Weak bearish
        else:
            ma_signal = 0.0  # Neutral

        # Normalise MA signal to [-1, 1] for blending
        ma_norm = ma_signal / 2.0

        # Try to blend with I3 structure data
        features = frames.get("features")
        has_structure = (
            isinstance(features, dict)
            and "trend_direction" in features
            and "trend_strength" in features
        )

        if has_structure:
            td = float(features["trend_direction"])
            ts = float(features["trend_strength"])
            structure_signal = td * ts  # [-1, +1] range
            blended = 0.5 * ma_norm + 0.5 * structure_signal

            # Confidence: agreement between MA and structure
            if ma_norm != 0 and structure_signal != 0:
                same_sign = (ma_norm > 0) == (structure_signal > 0)
                confidence = 1.0 if same_sign else 0.3
            elif ma_norm == 0 and structure_signal == 0:
                confidence = 0.5  # Both neutral
            else:
                confidence = 0.5  # One neutral, one has signal
        else:
            blended = ma_norm
            confidence = abs(ma_norm)  # Confidence = strength of MA signal alone

        # Classify into 5 states
        if blended > 0.5:
            trend_regime = 1.0
        elif blended > 0.1:
            trend_regime = 0.5
        elif blended >= -0.1:
            trend_regime = 0.0
        elif blended >= -0.5:
            trend_regime = -0.5
        else:
            trend_regime = -1.0

        # Price distance from SMA-20 as percentage
        price_vs_sma20_pct = (price - sma20) / sma20 * 100.0 if sma20 != 0 else 0.0

        return {
            "trend_regime": trend_regime,
            "trend_confidence": round(confidence, 4),
            "ma_alignment": ma_signal,
            "price_vs_sma20_pct": round(price_vs_sma20_pct, 4),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = TrendRegimePlugin()
