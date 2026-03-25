from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class ADXPlugin:
    """Average Directional Index with +DI/-DI (Wilder's method).

    ADX measures trend strength (0-100) regardless of direction.
    +DI/-DI measure bullish/bearish directional movement.
    """

    name: str = "ADX"
    outputs: frozenset[str] = frozenset({"adx_14", "plus_di_14", "minus_di_14"})
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    periods: list[int] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset(
            {key for p in self.periods for key in (f"adx_{p}", f"plus_di_{p}", f"minus_di_{p}")}
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < max(self.periods) * 2 + 1:
            return {}
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        out: dict[str, Any] = {}
        for p in self.periods:
            adx, plus_di, minus_di, state = self._adx_np(high, low, close, p)
            if adx is not None:
                out[f"adx_{p}"] = adx
                out[f"plus_di_{p}"] = plus_di
                out[f"minus_di_{p}"] = minus_di
                self._state[f"adx_{p}"] = state
        return out

    def _adx_np(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int
    ) -> tuple[float | None, float, float, dict[str, Any]]:
        """Compute ADX using Wilder's smoothing. Returns (adx, +DI, -DI, state)."""
        n = len(high)
        if n < period * 2 + 1:
            return None, 0.0, 0.0, {}

        # Directional Movement
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        tr = np.zeros(n)
        tr[0] = high[0] - low[0]

        for i in range(1, n):
            up_move = high[i] - high[i - 1]
            down_move = low[i - 1] - low[i]
            plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        # Wilder's smoothing (EMA with alpha=1/period)
        alpha = 1.0 / period

        # Seed: SMA of first `period` values (starting from index 1)
        smoothed_plus_dm = float(np.mean(plus_dm[1 : period + 1]))
        smoothed_minus_dm = float(np.mean(minus_dm[1 : period + 1]))
        smoothed_tr = float(np.mean(tr[1 : period + 1]))

        dx_values = []
        for i in range(period + 1, n):
            smoothed_plus_dm = (1 - alpha) * smoothed_plus_dm + alpha * plus_dm[i]
            smoothed_minus_dm = (1 - alpha) * smoothed_minus_dm + alpha * minus_dm[i]
            smoothed_tr = (1 - alpha) * smoothed_tr + alpha * tr[i]

            if smoothed_tr == 0:
                plus_di = 0.0
                minus_di = 0.0
            else:
                plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
                minus_di = 100.0 * smoothed_minus_dm / smoothed_tr

            di_sum = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0
            dx_values.append(dx)

        if len(dx_values) < period:
            return None, 0.0, 0.0, {}

        # ADX: Wilder's smoothing of DX
        adx = float(np.mean(dx_values[:period]))
        for dx in dx_values[period:]:
            adx = (1 - alpha) * adx + alpha * dx

        # Final +DI/-DI from last smoothed values
        if smoothed_tr == 0:
            final_plus_di = 0.0
            final_minus_di = 0.0
        else:
            final_plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
            final_minus_di = 100.0 * smoothed_minus_dm / smoothed_tr

        state = {
            "smoothed_plus_dm": smoothed_plus_dm,
            "smoothed_minus_dm": smoothed_minus_dm,
            "smoothed_tr": smoothed_tr,
            "adx": adx,
            "prev_high": float(high[-1]),
            "prev_low": float(low[-1]),
            "prev_close": float(close[-1]),
        }

        return float(adx), float(final_plus_di), float(final_minus_di), state

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])
        out: dict[str, Any] = {}

        for p in self.periods:
            key = f"adx_{p}"
            if key not in self._state:
                continue
            s = self._state[key]
            alpha = 1.0 / p

            # Directional Movement
            up_move = h - s["prev_high"]
            down_move = s["prev_low"] - lo
            pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
            mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr = max(h - lo, abs(h - s["prev_close"]), abs(lo - s["prev_close"]))

            # Wilder's smoothing
            s["smoothed_plus_dm"] = (1 - alpha) * s["smoothed_plus_dm"] + alpha * pdm
            s["smoothed_minus_dm"] = (1 - alpha) * s["smoothed_minus_dm"] + alpha * mdm
            s["smoothed_tr"] = (1 - alpha) * s["smoothed_tr"] + alpha * tr

            if s["smoothed_tr"] == 0:
                plus_di = 0.0
                minus_di = 0.0
            else:
                plus_di = 100.0 * s["smoothed_plus_dm"] / s["smoothed_tr"]
                minus_di = 100.0 * s["smoothed_minus_dm"] / s["smoothed_tr"]

            di_sum = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0

            # Smooth ADX
            s["adx"] = (1 - alpha) * s["adx"] + alpha * dx

            s["prev_high"] = h
            s["prev_low"] = lo
            s["prev_close"] = c

            out[f"adx_{p}"] = s["adx"]
            out[f"plus_di_{p}"] = plus_di
            out[f"minus_di_{p}"] = minus_di

        return out


plugin = ADXPlugin()
