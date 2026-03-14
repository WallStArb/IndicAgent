from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class KeltnerChannelsPlugin:
    """Keltner Channels: EMA +/- multiplier x ATR.

    Measures volatility-adjusted price channels. When Bollinger Bands
    contract inside Keltner Channels, a "squeeze" is forming.
    """

    name: str = "KeltnerChannels"
    outputs: set[str] = frozenset({"kc_upper_20", "kc_mid_20", "kc_lower_20"})
    min_lookback: int = 25
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 20
    atr_period: int = 20
    multiplier: float = 1.5
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"kc_upper_{self.period}",
                f"kc_mid_{self.period}",
                f"kc_lower_{self.period}",
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
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
        out = {
            f"kc_upper_{self.period}": mid + self.multiplier * atr_val,
            f"kc_mid_{self.period}": mid,
            f"kc_lower_{self.period}": mid - self.multiplier * atr_val,
        }
        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        df = frames.get("main")
        if df is None:
            return
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

        self._state = {
            "ema": float(ema.iloc[-1]),
            "atr": float(atr.iloc[-1]),
            "prev_close": float(close.iloc[-1]),
        }

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

        s = self._state
        # Update EMA
        alpha_ema = 2.0 / (self.period + 1)
        s["ema"] = alpha_ema * c + (1 - alpha_ema) * s["ema"]

        # Update ATR (Wilder's)
        alpha_atr = 1.0 / self.atr_period
        tr = max(h - lo, abs(h - s["prev_close"]), abs(lo - s["prev_close"]))
        s["atr"] = (1 - alpha_atr) * s["atr"] + alpha_atr * tr
        s["prev_close"] = c

        mid = s["ema"]
        return {
            f"kc_upper_{self.period}": mid + self.multiplier * s["atr"],
            f"kc_mid_{self.period}": mid,
            f"kc_lower_{self.period}": mid - self.multiplier * s["atr"],
        }


plugin = KeltnerChannelsPlugin()
