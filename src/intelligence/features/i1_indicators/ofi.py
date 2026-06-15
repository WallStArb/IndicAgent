"""Order Flow Imbalance (OFI) — I1 microstructure indicator.

Two computation paths:
- Tick path (primary): Uses raw tick data from market.ticks topic to compute
  buy/sell volume imbalance via tick rule. ofi_variant="tick".
- Proxy path (fallback): When tick_buffer is empty, uses bar-level OHLCV proxy
  `(close - low) / (high - low) * volume`. ofi_variant="proxy".

Outputs: ofi_ewma_5, ofi_ewma_20, ofi_divergence, ofi_spike_z, ofi_variant

ofi_divergence is a continuous z-score factor:
  ofi_divergence = ofi_spike_z - price_return_z
Both z-scores use a 100-bar rolling window. Positive = OFI more bullish than price.

State is keyed by (symbol, tf) from frames["__symbol__"] / frames["__timeframe__"]
to prevent cross-symbol contamination in multi-symbol deployments.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec

_PROXY_EPSILON: float = 1e-9
_HISTORY_MAXLEN: int = 100
_MIN_HISTORY: int = 5


@dataclass
class OFIPlugin:
    name: str = "ind_OFI"
    outputs: frozenset[str] = frozenset(
        {
            "ofi_ewma_5",
            "ofi_ewma_20",
            "ofi_divergence",
            "ofi_spike_z",
            "ofi_variant",
            "price_return_z",
        }
    )
    min_lookback: int = 5
    # Delegation pattern: compute_next delegates to compute_full (per-symbol self._state architecture)
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"volume", "microstructure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        tick_buf = frames.get("tick_buffer") or []
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

        if df is None or len(df) < self.min_lookback:
            return {}

        # Compute raw OFI — tick path or proxy
        if tick_buf:
            raw_ofi = self._compute_tick_ofi(tick_buf)
            variant = "tick"
        else:
            raw_ofi = self._compute_proxy_ofi(df)
            variant = "proxy"

        # Per-(symbol, tf) state
        state = self._state.setdefault(state_key, {})

        # OFI history for spike z-score
        ofi_history: deque = state.setdefault("ofi_history", deque(maxlen=_HISTORY_MAXLEN))
        ofi_history.append(raw_ofi)

        # Price return history for price_return_z — same 100-bar window
        close_series = df["close"]
        if len(close_series) >= 2:
            price_return = float(close_series.iloc[-1]) - float(close_series.iloc[-2])
        else:
            price_return = 0.0
        ret_history: deque = state.setdefault("ret_history", deque(maxlen=_HISTORY_MAXLEN))
        ret_history.append(price_return)

        # EWMA update
        alpha5 = 2.0 / (5 + 1)
        alpha20 = 2.0 / (20 + 1)
        state.setdefault("ewma5", raw_ofi)
        state.setdefault("ewma20", raw_ofi)
        state["ewma5"] = state["ewma5"] * (1 - alpha5) + raw_ofi * alpha5
        state["ewma20"] = state["ewma20"] * (1 - alpha20) + raw_ofi * alpha20

        # OFI z-score (exclude current bar from history for z-score base)
        if len(ofi_history) >= _MIN_HISTORY:
            hist = np.array(list(ofi_history))[:-1]
            mean_ofi = float(np.mean(hist))
            spike_z = (raw_ofi - mean_ofi) / (float(np.std(hist)) + 1e-9)
        else:
            spike_z = 0.0

        # Price return z-score (same structure)
        if len(ret_history) >= _MIN_HISTORY:
            ret_arr = np.array(list(ret_history))[:-1]
            mean_ret = float(np.mean(ret_arr))
            price_return_z = (price_return - mean_ret) / (float(np.std(ret_arr)) + 1e-9)
        else:
            price_return_z = 0.0

        # Continuous divergence factor: positive = OFI more bullish than price
        divergence = round(spike_z - price_return_z, 4)

        return {
            "ofi_ewma_5": round(float(state["ewma5"]), 6),
            "ofi_ewma_20": round(float(state["ewma20"]), 6),
            "ofi_divergence": divergence,
            "ofi_spike_z": round(spike_z, 4),
            "ofi_variant": variant,
            "price_return_z": round(price_return_z, 4),
            "_state": self._state,
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

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIPlugin()
