from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.trading.atr_utils import get_atr

from .swing_utils import find_swing_highs, find_swing_lows


@dataclass
class BOSCHoCHPlugin:
    """Break of Structure (BOS) and Change of Character (CHoCH).

    BOS: price closes beyond a swing high (bullish) or swing low (bearish).
    CHoCH: first BOS in the opposite direction of the prevailing trend,
    signaling a potential reversal.
    """

    name: str = "smc_BOSCHoCH"
    outputs: frozenset[str] = frozenset(
        {
            "bos_detected",
            "bos_direction",
            "bos_level",
            "bos_confidence",
            "choch_detected",
            "choch_direction",
            "smc_trend_direction",
            "bos_strength",
            "choch_strength",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=120),)
    neighbor: int = 5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
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
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        # ATR for strength normalization
        atr_14 = get_atr(features)
        has_atr = atr_14 is not None

        swing_highs = find_swing_highs(high, self.neighbor)
        swing_lows = find_swing_lows(low, self.neighbor)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {
                "bos_detected": 0.0,
                "bos_direction": 0.0,
                "bos_level": 0.0,
                "bos_confidence": 0.0,
                "choch_detected": 0.0,
                "choch_direction": 0.0,
                "smc_trend_direction": 0.0,
                "bos_strength": 0.0,
                "choch_strength": 0.0,
            }

        # Determine prevailing trend from swing structure
        trend = self._determine_trend(high, low, swing_highs, swing_lows)

        # Check for BOS: recent close beyond swing levels
        last_sh_price = float(high[swing_highs[-1]])
        last_sl_price = float(low[swing_lows[-1]])
        last_sh_idx = swing_highs[-1]
        last_sl_idx = swing_lows[-1]

        bos_detected = 0.0
        bos_direction = 0.0
        bos_level = 0.0
        bos_strength = 0.0

        # Check bars AFTER the most recent swing for breaks
        check_from = max(last_sh_idx, last_sl_idx) + 1
        for i in range(check_from, len(close)):
            if close[i] > last_sh_price:
                bos_detected = 1.0
                bos_direction = 1.0  # Bullish
                bos_level = last_sh_price
                # Gradient: break distance / ATR
                if has_atr:
                    bos_strength = max(0.0, (float(close[i]) - last_sh_price) / atr_14)
                break
            if close[i] < last_sl_price:
                bos_detected = 1.0
                bos_direction = -1.0  # Bearish
                bos_level = last_sl_price
                # Gradient: break distance / ATR
                if has_atr:
                    bos_strength = max(0.0, (last_sl_price - float(close[i])) / atr_14)
                break

        # CHoCH: BOS in opposite direction to prevailing trend
        choch_detected = 0.0
        choch_direction = 0.0
        choch_strength = 0.0
        if bos_detected == 1.0 and trend != 0.0:
            if bos_direction != trend:
                choch_detected = 1.0
                choch_direction = bos_direction
                choch_strength = bos_strength  # same break magnitude

        return {
            "bos_detected": bos_detected,
            "bos_direction": bos_direction,
            "bos_level": bos_level,
            "bos_confidence": bos_strength,
            "choch_detected": choch_detected,
            "choch_direction": choch_direction,
            "smc_trend_direction": trend,
            "bos_strength": bos_strength,
            "choch_strength": choch_strength,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _determine_trend(
        high: np.ndarray,
        low: np.ndarray,
        swing_highs: list[int],
        swing_lows: list[int],
    ) -> float:
        """Determine trend from last 2 swing highs and 2 swing lows."""
        hh = 0.0
        if len(swing_highs) >= 2:
            hh = 1.0 if high[swing_highs[-1]] > high[swing_highs[-2]] else -1.0

        hl = 0.0
        if len(swing_lows) >= 2:
            hl = 1.0 if low[swing_lows[-1]] > low[swing_lows[-2]] else -1.0

        if hh == 1.0 and hl == 1.0:
            return 1.0  # Uptrend
        elif hh == -1.0 and hl == -1.0:
            return -1.0  # Downtrend
        return 0.0  # Neutral


plugin = BOSCHoCHPlugin()
