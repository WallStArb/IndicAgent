"""ADX (Average Directional Index) plugin -- migrated to IncrementalMixin.

This plugin demonstrates the IncrementalMixin pattern for the Wilder's accumulator
archetype (same as ATR):
- _compute_full_core: full ADX computation over entire history, returns outputs only (no _state)
- _compute_next_core: incremental single-bar update using wilders_update, mutates state in place
- _seed_state: extracts {smoothed_plus_dm, smoothed_minus_dm, smoothed_tr, adx, prev_high,
  prev_low, prev_close} per period from the full computation

The mixin provides compute_full and compute_next -- ADXPlugin defines none of these directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, wilders_update


@dataclass
class ADXPlugin(IncrementalMixin):
    """Average Directional Index with +DI/-DI (Wilder's method).

    ADX measures trend strength (0-100) regardless of direction.
    +DI/-DI measure bullish/bearish directional movement.

    Uses IncrementalMixin to own the state contract. Implements:
    - _compute_full_core: batch ADX computation via Wilder's smoothing
    - _compute_next_core: single-bar incremental update via wilders_update
    - _seed_state: seeds {smoothed_plus_dm, smoothed_minus_dm, smoothed_tr, adx,
      prev_high, prev_low, prev_close} per period
    """

    name: str = "ADX"
    outputs: frozenset[str] = frozenset({"adx_14", "plus_di_14", "minus_di_14"})
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=200),)
    periods: list[int] = None

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset(
            {key for p in self.periods for key in (f"adx_{p}", f"plus_di_{p}", f"minus_di_{p}")}
        )

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute ADX for all periods over full history.

        Returns output values only -- no _state key. The mixin calls
        _seed_state separately to attach state.

        Returns:
            Dict of {f"adx_{p}": float, f"plus_di_{p}": float, f"minus_di_{p}": float}
            for each period. Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) < max(self.periods) * 2 + 1:
            return {}
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        out: dict[str, Any] = {}
        for p in self.periods:
            adx, plus_di, minus_di, _ = self._adx_np(high, low, close, p)
            if adx is not None:
                out[f"adx_{p}"] = adx
                out[f"plus_di_{p}"] = plus_di
                out[f"minus_di_{p}"] = minus_di
        return out

    def _adx_np(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int
    ) -> tuple[float | None, float, float, dict]:
        """Compute ADX using Wilder's smoothing. Returns (adx, +DI, -DI, state_dict).

        state_dict contains the Wilder accumulators needed for incremental updates:
        {smoothed_plus_dm, smoothed_minus_dm, smoothed_tr, adx, prev_high, prev_low, prev_close}.
        Returns empty state_dict {} when data is insufficient.
        """
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
        # Seed: SMA of first `period` values (starting from index 1)
        smoothed_plus_dm = float(np.mean(plus_dm[1 : period + 1]))
        smoothed_minus_dm = float(np.mean(minus_dm[1 : period + 1]))
        smoothed_tr = float(np.mean(tr[1 : period + 1]))

        dx_values = []
        for i in range(period + 1, n):
            smoothed_plus_dm = wilders_update(smoothed_plus_dm, plus_dm[i], period)
            smoothed_minus_dm = wilders_update(smoothed_minus_dm, minus_dm[i], period)
            smoothed_tr = wilders_update(smoothed_tr, tr[i], period)

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
            adx = wilders_update(adx, dx, period)

        # Final +DI/-DI from last smoothed values
        if smoothed_tr == 0:
            final_plus_di = 0.0
            final_minus_di = 0.0
        else:
            final_plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
            final_minus_di = 100.0 * smoothed_minus_dm / smoothed_tr

        state_dict = {
            "smoothed_plus_dm": smoothed_plus_dm,
            "smoothed_minus_dm": smoothed_minus_dm,
            "smoothed_tr": smoothed_tr,
            "adx": adx,
            "prev_high": float(high[-1]),
            "prev_low": float(low[-1]),
            "prev_close": float(close[-1]),
        }
        return float(adx), float(final_plus_di), float(final_minus_di), state_dict

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Extract incremental state from frames after full computation.

        Delegates to _adx_np (the authoritative implementation) to avoid
        duplicating the Wilder's smoothing loop. Returns a nested state dict
        keyed by period: {f"adx_{p}": {smoothed_plus_dm, smoothed_minus_dm,
        smoothed_tr, adx, prev_high, prev_low, prev_close}}.

        Args:
            frames: Same frames dict passed to _compute_full_core.

        Returns:
            State dict with Wilder accumulators and previous bar values per period.
        """
        df = frames.get("main")
        if df is None or len(df) < max(self.periods) * 2 + 1:
            return {}
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        state: dict[str, Any] = {}
        for p in self.periods:
            adx, _, _, p_state = self._adx_np(high, low, close, p)
            if adx is not None:
                state[f"adx_{p}"] = p_state
        return state

    def _compute_next_core(
        self, frames: dict[str, pd.DataFrame], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Incremental single-bar ADX update using Wilder's smoothing.

        State is guaranteed non-None by the mixin. Mutates state in place.

        Args:
            frames: Plugin frames dict. Executor passes full historical frames.
            state:  Mutable state dict. Expected keys: {f"adx_{p}": {smoothed_plus_dm,
                    smoothed_minus_dm, smoothed_tr, adx, prev_high, prev_low, prev_close}}

        Returns:
            Dict of {f"adx_{p}": float, f"plus_di_{p}": float, f"minus_di_{p}": float}
            for periods present in state. Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])
        out: dict[str, Any] = {}

        for p in self.periods:
            key = f"adx_{p}"
            if key not in state:
                continue
            s = state[key]

            # Directional Movement
            up_move = h - s["prev_high"]
            down_move = s["prev_low"] - lo
            pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
            mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr = max(h - lo, abs(h - s["prev_close"]), abs(lo - s["prev_close"]))

            # Wilder's smoothing via shared utility
            s["smoothed_plus_dm"] = wilders_update(s["smoothed_plus_dm"], pdm, p)
            s["smoothed_minus_dm"] = wilders_update(s["smoothed_minus_dm"], mdm, p)
            s["smoothed_tr"] = wilders_update(s["smoothed_tr"], tr, p)

            if s["smoothed_tr"] == 0:
                plus_di = 0.0
                minus_di = 0.0
            else:
                plus_di = 100.0 * s["smoothed_plus_dm"] / s["smoothed_tr"]
                minus_di = 100.0 * s["smoothed_minus_dm"] / s["smoothed_tr"]

            di_sum = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0

            # Smooth ADX via Wilder's
            s["adx"] = wilders_update(s["adx"], dx, p)

            s["prev_high"] = h
            s["prev_low"] = lo
            s["prev_close"] = c

            out[f"adx_{p}"] = s["adx"]
            out[f"plus_di_{p}"] = plus_di
            out[f"minus_di_{p}"] = minus_di

        return out


plugin = ADXPlugin()
