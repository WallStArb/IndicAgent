from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec


@dataclass
class BollingerSqueezePlugin:
    name: str = "BollingerSqueeze"
    outputs: frozenset[str] = frozenset(
        {"squeeze_active", "squeeze_duration", "squeeze_bandwidth_pctile", "squeeze_fired"}
    )
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"pattern", "volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    bb_period: int = 20
    bb_std: float = 2.0
    kc_period: int = 20
    kc_mult: float = 1.5
    bandwidth_history_len: int = 100
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        # Bollinger Bands
        sma = pd.Series(close).rolling(self.bb_period).mean().to_numpy()
        std = pd.Series(close).rolling(self.bb_period).std(ddof=0).to_numpy()
        bb_upper = sma + self.bb_std * std
        bb_lower = sma - self.bb_std * std

        # Keltner Channels (ATR-based)
        atr = self._atr_series(high, low, close, self.kc_period)
        kc_upper = sma + self.kc_mult * atr
        kc_lower = sma - self.kc_mult * atr

        # Squeeze detection across all valid bars
        valid_start = max(self.bb_period, self.kc_period)
        squeeze_count = 0
        bandwidth_history: deque[float] = deque(maxlen=self.bandwidth_history_len)

        for i in range(valid_start, len(close)):
            in_squeeze = bb_upper[i] < kc_upper[i] and bb_lower[i] > kc_lower[i]
            if in_squeeze:
                squeeze_count += 1
            else:
                squeeze_count = 0
            if sma[i] != 0:
                bandwidth_history.append((bb_upper[i] - bb_lower[i]) / sma[i])

        # Current bar state
        last = len(close) - 1
        current_squeeze = bb_upper[last] < kc_upper[last] and bb_lower[last] > kc_lower[last]
        current_bw = (bb_upper[last] - bb_lower[last]) / sma[last] if sma[last] != 0 else 0.0

        # Bandwidth percentile
        bw_pctile = 0.5
        if bandwidth_history:
            bw_list = sorted(bandwidth_history)
            rank = sum(1 for b in bw_list if b <= current_bw)
            bw_pctile = rank / len(bw_list)

        # Squeeze fired: was in squeeze at bar N-1, not in squeeze at bar N
        prev_bar = last - 1
        fired = 0.0
        if prev_bar >= valid_start:
            was_squeeze = (
                bb_upper[prev_bar] < kc_upper[prev_bar] and bb_lower[prev_bar] > kc_lower[prev_bar]
            )
            if was_squeeze and not current_squeeze:
                fired = 1.0

        # Seed incremental state
        self._state = {
            "squeeze_count": squeeze_count if current_squeeze else 0,
            "prev_squeeze": current_squeeze,
            "bandwidth_history": bandwidth_history,
            "close_window": deque(close[-self.bb_period :], maxlen=self.bb_period),
            "high_window": deque(high[-self.kc_period :], maxlen=self.kc_period),
            "low_window": deque(low[-self.kc_period :], maxlen=self.kc_period),
            "prev_close": float(close[-1]),
        }

        return {
            "squeeze_active": 1.0 if current_squeeze else 0.0,
            "squeeze_duration": float(squeeze_count if current_squeeze else 0),
            "squeeze_bandwidth_pctile": bw_pctile,
            "squeeze_fired": fired,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        c = float(row["close"])
        h = float(row["high"])
        lo = float(row["low"])

        s = self._state
        s["close_window"].append(c)
        s["high_window"].append(h)
        s["low_window"].append(lo)

        if len(s["close_window"]) < self.bb_period:
            return {}

        # BB from close window
        cw = list(s["close_window"])
        mean_c = sum(cw) / len(cw)
        var_c = sum((x - mean_c) ** 2 for x in cw) / len(cw)
        std_c = var_c**0.5
        bb_upper = mean_c + self.bb_std * std_c
        bb_lower = mean_c - self.bb_std * std_c

        # ATR from high/low/close windows
        hw = list(s["high_window"])
        lw = list(s["low_window"])
        # Simple ATR approximation: average TR over window
        trs = []
        prev_c = s["prev_close"]
        for i in range(len(hw)):
            t = max(hw[i] - lw[i], abs(hw[i] - prev_c), abs(lw[i] - prev_c))
            prev_c = cw[i] if i < len(cw) else c
            trs.append(t)
        atr = sum(trs) / len(trs) if trs else 0.0

        kc_upper = mean_c + self.kc_mult * atr
        kc_lower = mean_c - self.kc_mult * atr

        current_squeeze = bb_upper < kc_upper and bb_lower > kc_lower
        if current_squeeze:
            s["squeeze_count"] = s.get("squeeze_count", 0) + 1
        else:
            s["squeeze_count"] = 0

        # Bandwidth
        bw = (bb_upper - bb_lower) / mean_c if mean_c != 0 else 0.0
        s["bandwidth_history"].append(bw)
        bw_list = sorted(s["bandwidth_history"])
        rank = sum(1 for b in bw_list if b <= bw)
        bw_pctile = rank / len(bw_list)

        # Fired
        fired = 1.0 if s["prev_squeeze"] and not current_squeeze else 0.0
        s["prev_squeeze"] = current_squeeze
        s["prev_close"] = c

        return {
            "squeeze_active": 1.0 if current_squeeze else 0.0,
            "squeeze_duration": float(s["squeeze_count"]),
            "squeeze_bandwidth_pctile": bw_pctile,
            "squeeze_fired": fired,
        }

    @staticmethod
    def _atr_series(
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        period: int,
    ) -> np.ndarray:
        """Compute ATR series using simple moving average of True Range."""
        tr = np.zeros(len(close))
        tr[0] = high[0] - low[0]
        for i in range(1, len(close)):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        atr = pd.Series(tr).rolling(period).mean().to_numpy()
        return atr


plugin = BollingerSqueezePlugin()
