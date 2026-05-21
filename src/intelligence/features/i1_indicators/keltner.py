"""Keltner Channels plugin -- migrated to IncrementalMixin.

Uses the EMA chain + ATR hybrid archetype:
- _compute_full_core: full Keltner computation via ewm pandas operations
- _compute_next_core: incremental update using update_ema() and wilders_update()
- _seed_state: extracts {ema, atr, prev_close} from full computation

The mixin provides compute_full and compute_next -- KeltnerChannelsPlugin defines none directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, update_ema, wilders_update


@dataclass
class KeltnerChannelsPlugin(IncrementalMixin):
    """Keltner Channels: EMA +/- multiplier x ATR.

    Measures volatility-adjusted price channels. When Bollinger Bands
    contract inside Keltner Channels, a "squeeze" is forming.

    Uses IncrementalMixin to own the state contract. Implements:
    - _compute_full_core: batch Keltner via ewm pandas operations
    - _compute_next_core: single-bar incremental update using update_ema and wilders_update
    - _seed_state: seeds {ema, atr, prev_close}
    """

    name: str = "KeltnerChannels"
    outputs: frozenset[str] = frozenset({"kc_upper_20", "kc_mid_20", "kc_lower_20"})
    min_lookback: int = 25
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    period: int = 20
    atr_period: int = 20
    multiplier: float = 1.5

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"kc_upper_{self.period}",
                f"kc_mid_{self.period}",
                f"kc_lower_{self.period}",
            }
        )

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute Keltner Channels over full history.

        Returns output values only -- no _state key. The mixin calls
        _seed_state separately to attach state.

        Returns:
            Dict of {kc_upper, kc_mid, kc_lower} keyed by period.
            Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) < max(self.period, self.atr_period) + 1:
            return {}
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # EMA of close
        ema = close.ewm(span=self.period, adjust=False, min_periods=self.period).mean()

        # ATR via Wilder's smoothing
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / self.atr_period, adjust=False, min_periods=self.atr_period).mean()

        mid = float(ema.iloc[-1])
        atr_val = float(atr.iloc[-1])
        return {
            f"kc_upper_{self.period}": mid + self.multiplier * atr_val,
            f"kc_mid_{self.period}": mid,
            f"kc_lower_{self.period}": mid - self.multiplier * atr_val,
        }

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Extract EMA and ATR state for incremental Keltner updates.

        Args:
            frames: Same frames dict passed to _compute_full_core.

        Returns:
            State dict with {ema, atr, prev_close}.
        """
        df = frames.get("main")
        if df is None or len(df) < max(self.period, self.atr_period) + 1:
            return {}
        close = df["close"]
        high = df["high"]
        low = df["low"]

        ema = close.ewm(span=self.period, adjust=False, min_periods=self.period).mean()

        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / self.atr_period, adjust=False, min_periods=self.atr_period).mean()

        return {
            "ema": float(ema.iloc[-1]),
            "atr": float(atr.iloc[-1]),
            "prev_close": float(close.iloc[-1]),
        }

    def _compute_next_core(
        self, frames: dict[str, pd.DataFrame], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Incremental single-bar Keltner update using shared EMA and ATR utilities.

        State is guaranteed non-None by the mixin. Mutates state in place.

        Args:
            frames: Plugin frames dict. Executor passes full historical frames.
            state:  Mutable state dict. Expected keys: {ema, atr, prev_close}.

        Returns:
            Dict of {kc_upper, kc_mid, kc_lower} keyed by period.
            Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])

        # Update EMA via shared utility
        state["ema"] = update_ema(c, state["ema"], self.period)

        # Update ATR via shared Wilder's utility
        tr = max(h - lo, abs(h - state["prev_close"]), abs(lo - state["prev_close"]))
        state["atr"] = wilders_update(state["atr"], tr, self.atr_period)
        state["prev_close"] = c

        mid = state["ema"]
        return {
            f"kc_upper_{self.period}": mid + self.multiplier * state["atr"],
            f"kc_mid_{self.period}": mid,
            f"kc_lower_{self.period}": mid - self.multiplier * state["atr"],
        }


plugin = KeltnerChannelsPlugin()
