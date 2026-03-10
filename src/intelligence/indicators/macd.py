from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class MACDPlugin:
    name: str = "MACD"
    outputs: set[str] = frozenset({"macd_12_26_9", "macd_signal_12_26_9", "macd_histogram_12_26_9"})
    min_lookback: int = 50
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    configs: list[tuple] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.configs:
            self.configs = [(12, 26, 9)]
        self.outputs = frozenset(
            {
                key
                for (f, s, sig) in self.configs
                for key in (
                    f"macd_{f}_{s}_{sig}",
                    f"macd_signal_{f}_{s}_{sig}",
                    f"macd_histogram_{f}_{s}_{sig}",
                )
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None:
            return {}
        close = df["close"]
        out: dict[str, Any] = {}
        for fast, slow, signal in self.configs:
            if len(close) < slow + signal + 1:
                continue
            ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
            ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
            macd_line = ema_fast - ema_slow
            macd_signal = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
            macd_hist = macd_line - macd_signal
            out[f"macd_{fast}_{slow}_{signal}"] = float(macd_line.iloc[-1])
            out[f"macd_signal_{fast}_{slow}_{signal}"] = float(macd_signal.iloc[-1])
            out[f"macd_histogram_{fast}_{slow}_{signal}"] = float(macd_hist.iloc[-1])
        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        """Extract EMA state for incremental MACD updates."""
        df = frames.get("main")
        if df is None:
            return
        close = df["close"]
        for fast, slow, signal in self.configs:
            if len(close) < slow + signal + 1:
                continue
            ema_fast_series = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
            ema_slow_series = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
            macd_line = ema_fast_series - ema_slow_series
            macd_signal_series = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()

            key = f"macd_{fast}_{slow}_{signal}"
            self._state[key] = {
                "ema_fast": float(ema_fast_series.iloc[-1]),
                "ema_slow": float(ema_slow_series.iloc[-1]),
                "ema_signal": float(macd_signal_series.iloc[-1]),
            }

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        new_close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}
        for fast, slow, signal in self.configs:
            key = f"macd_{fast}_{slow}_{signal}"
            if key not in self._state:
                continue
            s = self._state[key]
            # Update fast EMA
            alpha_fast = 2.0 / (fast + 1)
            s["ema_fast"] = alpha_fast * new_close + (1 - alpha_fast) * s["ema_fast"]
            # Update slow EMA
            alpha_slow = 2.0 / (slow + 1)
            s["ema_slow"] = alpha_slow * new_close + (1 - alpha_slow) * s["ema_slow"]
            # MACD line
            macd_val = s["ema_fast"] - s["ema_slow"]
            # Update signal EMA
            alpha_sig = 2.0 / (signal + 1)
            s["ema_signal"] = alpha_sig * macd_val + (1 - alpha_sig) * s["ema_signal"]
            # Histogram
            histogram = macd_val - s["ema_signal"]

            out[f"macd_{fast}_{slow}_{signal}"] = macd_val
            out[f"macd_signal_{fast}_{slow}_{signal}"] = s["ema_signal"]
            out[f"macd_histogram_{fast}_{slow}_{signal}"] = histogram
        return out


plugin = MACDPlugin()
