from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class OrderBlocksPlugin:
    """Order Blocks — last opposing candle before an impulsive move.

    Bullish OB: last bearish candle before a bullish impulse.
    Bearish OB: last bullish candle before a bearish impulse.
    These zones represent institutional entry points and act as S/R.
    """

    name: str = "smc_OrderBlocks"
    outputs: frozenset[str] = frozenset(
        {
            "ob_type",
            "ob_top",
            "ob_bottom",
            "ob_strength",
            "ob_mitigated",
            "ob_distance_pct",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    impulse_bars: int = 3  # Minimum consecutive bars for an impulse
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        open_ = df["open"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        current_price = float(close[-1])
        avg_volume = float(np.mean(volume))

        # Find impulsive moves and their order blocks
        order_blocks: list[dict[str, Any]] = []

        i = self.impulse_bars
        while i < len(df):
            # Check for bullish impulse: N consecutive bullish candles
            bullish_run = 0
            for j in range(i - self.impulse_bars, i):
                if j >= 0 and close[j] > open_[j]:
                    bullish_run += 1
                else:
                    break

            if bullish_run >= self.impulse_bars:
                impulse_start = i - self.impulse_bars
                impulse_move = close[i - 1] - open_[impulse_start]
                impulse_vol = float(np.mean(volume[impulse_start:i]))

                # Significant move check (at least 0.3% of price)
                if abs(impulse_move) > current_price * 0.003:
                    # Find last bearish candle before impulse
                    ob_idx = None
                    for k in range(impulse_start - 1, max(0, impulse_start - 10), -1):
                        if close[k] < open_[k]:  # Bearish candle
                            ob_idx = k
                            break

                    if ob_idx is not None:
                        strength = min(1.0, impulse_vol / avg_volume) if avg_volume > 0 else 0.5
                        mitigated = self._check_mitigated(low, float(low[ob_idx]), i, len(df))
                        order_blocks.append(
                            {
                                "type": 1.0,
                                "top": float(high[ob_idx]),
                                "bottom": float(low[ob_idx]),
                                "strength": strength,
                                "mitigated": mitigated,
                                "idx": ob_idx,
                            }
                        )

            # Check for bearish impulse
            bearish_run = 0
            for j in range(i - self.impulse_bars, i):
                if j >= 0 and close[j] < open_[j]:
                    bearish_run += 1
                else:
                    break

            if bearish_run >= self.impulse_bars:
                impulse_start = i - self.impulse_bars
                impulse_move = close[i - 1] - open_[impulse_start]
                impulse_vol = float(np.mean(volume[impulse_start:i]))

                if abs(impulse_move) > current_price * 0.003:
                    ob_idx = None
                    for k in range(impulse_start - 1, max(0, impulse_start - 10), -1):
                        if close[k] > open_[k]:  # Bullish candle
                            ob_idx = k
                            break

                    if ob_idx is not None:
                        strength = min(1.0, impulse_vol / avg_volume) if avg_volume > 0 else 0.5
                        mitigated = self._check_mitigated(
                            high, float(high[ob_idx]), i, len(df), bearish=True
                        )
                        order_blocks.append(
                            {
                                "type": -1.0,
                                "top": float(high[ob_idx]),
                                "bottom": float(low[ob_idx]),
                                "strength": strength,
                                "mitigated": mitigated,
                                "idx": ob_idx,
                            }
                        )

            i += 1

        # Filter to unmitigated OBs and return most recent
        active_obs = [ob for ob in order_blocks if ob["mitigated"] == 0.0]

        if not active_obs:
            return {
                "ob_type": 0.0,
                "ob_top": 0.0,
                "ob_bottom": 0.0,
                "ob_strength": 0.0,
                "ob_mitigated": 0.0,
                "ob_distance_pct": 0.0,
            }

        latest = active_obs[-1]
        ob_mid = (latest["top"] + latest["bottom"]) / 2
        dist_pct = abs(current_price - ob_mid) / current_price * 100 if current_price != 0 else 0.0

        return {
            "ob_type": latest["type"],
            "ob_top": latest["top"],
            "ob_bottom": latest["bottom"],
            "ob_strength": latest["strength"],
            "ob_mitigated": latest["mitigated"],
            "ob_distance_pct": dist_pct,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _check_mitigated(
        price_array: np.ndarray,
        ob_level: float,
        impulse_end: int,
        n: int,
        bearish: bool = False,
    ) -> float:
        """Check if price traded through the OB zone after the impulse."""
        for j in range(impulse_end, n):
            if bearish and price_array[j] >= ob_level:
                return 1.0
            elif not bearish and price_array[j] <= ob_level:
                return 1.0
        return 0.0


plugin = OrderBlocksPlugin()
