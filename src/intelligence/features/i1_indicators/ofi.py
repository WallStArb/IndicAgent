"""Order Flow Imbalance (OFI) — I1 microstructure indicator.

Two computation paths:
- Tick path (primary): Uses raw tick data from market.ticks topic to compute
  buy/sell volume imbalance via tick rule. ofi_variant="tick".
- Proxy path (fallback): When tick_buffer is empty, uses bar-level OHLCV proxy
  `(close - low) / (high - low) * volume`. ofi_variant="proxy".

Outputs: ofi_ewma_5, ofi_ewma_20, ofi_divergence, ofi_spike_z, ofi_variant
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec

_PROXY_EPSILON: float = 1e-9


@dataclass
class OFIPlugin:
    name: str = "ind_OFI"
    outputs: frozenset[str] = frozenset(
        {"ofi_ewma_5", "ofi_ewma_20", "ofi_divergence", "ofi_spike_z", "ofi_variant"}
    )
    min_lookback: int = 5
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume", "microstructure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        tick_buf = frames.get("tick_buffer") or []

        if df is None or len(df) < self.min_lookback:
            return {}

        # Compute raw OFI — tick path or proxy
        if tick_buf:
            raw_ofi = self._compute_tick_ofi(tick_buf)
            variant = "tick"
        else:
            raw_ofi = self._compute_proxy_ofi(df)
            variant = "proxy"

        # Update OFI history for z-score
        if "ofi_history" not in self._state:
            self._state["ofi_history"] = deque(maxlen=100)
        self._state["ofi_history"].append(raw_ofi)

        # EWMA update
        alpha5 = 2.0 / (5 + 1)
        alpha20 = 2.0 / (20 + 1)
        if "ewma5" not in self._state:
            self._state["ewma5"] = raw_ofi
        if "ewma20" not in self._state:
            self._state["ewma20"] = raw_ofi
        self._state["ewma5"] = self._state["ewma5"] * (1 - alpha5) + raw_ofi * alpha5
        self._state["ewma20"] = self._state["ewma20"] * (1 - alpha20) + raw_ofi * alpha20

        # Z-score: compare raw_ofi vs history of all-but-last
        history = list(self._state["ofi_history"])
        if len(history) >= 5:
            hist_arr = np.array(history[:-1])  # exclude current bar
            mean = float(np.mean(hist_arr))
            std = float(np.std(hist_arr)) + 1e-9
            spike_z = (raw_ofi - mean) / std
        else:
            spike_z = 0.0

        # Divergence: sign of raw_ofi vs sign of price change
        close_series = df["close"]
        if len(close_series) >= 2:
            price_change = float(close_series.iloc[-1]) - float(close_series.iloc[-2])
            price_dir = 1 if price_change > 0 else (-1 if price_change < 0 else 0)
        else:
            price_dir = 0
        ofi_dir = 1 if raw_ofi > 0 else (-1 if raw_ofi < 0 else 0)
        divergence = float(ofi_dir - price_dir)

        self._state["prev_close"] = float(df["close"].iloc[-1])

        return {
            "ofi_ewma_5": round(float(self._state["ewma5"]), 6),
            "ofi_ewma_20": round(float(self._state["ewma20"]), 6),
            "ofi_divergence": round(divergence, 4),
            "ofi_spike_z": round(spike_z, 4),
            "ofi_variant": variant,
        }

    def _compute_tick_ofi(self, tick_buf: list[dict]) -> float:
        """Tick rule: buy_vol - sell_vol from sequential tick price changes."""
        buy_vol = 0.0
        sell_vol = 0.0
        prev_price: float | None = None
        for tick in tick_buf:
            try:
                price = float(tick.get("price", 0) or 0)
                size = float(tick.get("size") or 0)
            except (TypeError, ValueError):
                continue
            if prev_price is not None:
                if price > prev_price:
                    buy_vol += size
                elif price < prev_price:
                    sell_vol += size
                # equal: neutral, no contribution
            prev_price = price
        return buy_vol - sell_vol

    def _compute_proxy_ofi(self, df: pd.DataFrame) -> float:
        """Bar-level proxy: (close - low) / (high - low + epsilon) * volume."""
        row = df.iloc[-1]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        volume = float(row["volume"])
        return (close - low) / (high - low + _PROXY_EPSILON) * volume

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIPlugin()
