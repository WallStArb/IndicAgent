from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class ROCPPOPlugin:
    """Rate of Change (ROC) and Percentage Price Oscillator (PPO).

    ROC: ((close - close_n) / close_n) * 100  (simple % change over N periods)
    PPO: ((EMA_fast - EMA_slow) / EMA_slow) * 100  (normalized MACD)

    PPO is MACD expressed as a percentage, enabling cross-instrument comparison.
    """

    name: str = "ROC_PPO"
    outputs: frozenset[str] = frozenset({"roc_14", "ppo_12_26", "ppo_signal_12_26"})
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    roc_period: int = 14
    ppo_fast: int = 12
    ppo_slow: int = 26
    ppo_signal: int = 9
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"roc_{self.roc_period}",
                f"ppo_{self.ppo_fast}_{self.ppo_slow}",
                f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}",
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.ppo_slow + self.ppo_signal + 1:
            return {}
        close = df["close"]
        out: dict[str, Any] = {}

        # ROC
        if len(close) > self.roc_period:
            current = float(close.iloc[-1])
            past = float(close.iloc[-1 - self.roc_period])
            out[f"roc_{self.roc_period}"] = 100.0 * (current - past) / past if past != 0 else 0.0

        # PPO = (EMA_fast - EMA_slow) / EMA_slow * 100
        ema_fast = close.ewm(span=self.ppo_fast, adjust=False, min_periods=self.ppo_fast).mean()
        ema_slow = close.ewm(span=self.ppo_slow, adjust=False, min_periods=self.ppo_slow).mean()
        ppo_line = (ema_fast - ema_slow) / ema_slow * 100
        ppo_sig = ppo_line.ewm(
            span=self.ppo_signal, adjust=False, min_periods=self.ppo_signal
        ).mean()

        out[f"ppo_{self.ppo_fast}_{self.ppo_slow}"] = float(ppo_line.iloc[-1])
        out[f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}"] = float(ppo_sig.iloc[-1])

        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        df = frames.get("main")
        if df is None:
            return
        close = df["close"]

        # ROC state: keep a deque of recent closes for lookback
        recent = close.iloc[-self.roc_period - 1 :].tolist()
        roc_window = deque(recent, maxlen=self.roc_period + 1)

        # PPO state: EMA values
        ema_fast = close.ewm(span=self.ppo_fast, adjust=False, min_periods=self.ppo_fast).mean()
        ema_slow = close.ewm(span=self.ppo_slow, adjust=False, min_periods=self.ppo_slow).mean()
        ppo_line = (ema_fast - ema_slow) / ema_slow * 100
        ppo_sig = ppo_line.ewm(
            span=self.ppo_signal, adjust=False, min_periods=self.ppo_signal
        ).mean()

        self._state = {
            "roc_window": roc_window,
            "ema_fast": float(ema_fast.iloc[-1]),
            "ema_slow": float(ema_slow.iloc[-1]),
            "ppo_signal_ema": float(ppo_sig.iloc[-1]),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        c = float(df["close"].iloc[-1])
        s = self._state
        out: dict[str, Any] = {}

        # ROC: % change from N bars ago
        s["roc_window"].append(c)
        if len(s["roc_window"]) == self.roc_period + 1:
            past = s["roc_window"][0]
            out[f"roc_{self.roc_period}"] = 100.0 * (c - past) / past if past != 0 else 0.0

        # PPO: update EMAs
        alpha_fast = 2.0 / (self.ppo_fast + 1)
        alpha_slow = 2.0 / (self.ppo_slow + 1)
        s["ema_fast"] = alpha_fast * c + (1 - alpha_fast) * s["ema_fast"]
        s["ema_slow"] = alpha_slow * c + (1 - alpha_slow) * s["ema_slow"]

        ppo_val = (
            100.0 * (s["ema_fast"] - s["ema_slow"]) / s["ema_slow"] if s["ema_slow"] != 0 else 0.0
        )

        alpha_sig = 2.0 / (self.ppo_signal + 1)
        s["ppo_signal_ema"] = alpha_sig * ppo_val + (1 - alpha_sig) * s["ppo_signal_ema"]

        out[f"ppo_{self.ppo_fast}_{self.ppo_slow}"] = ppo_val
        out[f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}"] = s["ppo_signal_ema"]

        return out


plugin = ROCPPOPlugin()
