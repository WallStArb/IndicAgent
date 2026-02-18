from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class GARCHVolatilityPlugin:
    """GARCH(1,1) conditional volatility forecast.

    Forecasts next-bar volatility. Forward-looking complement to the
    backward-looking VolatilityRegime plugin.

    sigma2_t = omega + alpha * epsilon_{t-1}^2 + beta * sigma2_{t-1}
    """

    name: str = "ctx_GARCHVolatility"
    outputs: set[str] = frozenset(
        {"garch_sigma", "garch_vol_ratio", "garch_vol_regime", "garch_shock"}
    )
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"context", "volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    omega: float = 0.00001
    alpha: float = 0.10
    beta: float = 0.85
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        # Log returns
        log_returns = np.log(close[1:] / close[:-1])
        log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)

        # Initialize sigma2 with variance of first 20 returns
        init_window = min(20, len(log_returns))
        sigma2 = float(np.var(log_returns[:init_window]))
        if sigma2 == 0:
            sigma2 = self.omega / (1 - self.alpha - self.beta)

        # Rolling realized vol (std of last 20 log returns)
        realized_returns: deque[float] = deque(maxlen=20)

        # GARCH recursion
        sigma_history: list[float] = []
        for i in range(len(log_returns)):
            epsilon = log_returns[i]
            sigma2 = self.omega + self.alpha * epsilon**2 + self.beta * sigma2
            sigma_history.append(math.sqrt(sigma2))
            realized_returns.append(epsilon)

        garch_sigma = sigma_history[-1]

        # Realized volatility from last 20 returns
        if len(realized_returns) >= 2:
            realized_vol = float(np.std(list(realized_returns)))
        else:
            realized_vol = garch_sigma

        # Vol ratio: >1 means GARCH forecasts expansion
        vol_ratio = garch_sigma / realized_vol if realized_vol > 1e-10 else 1.0

        # Regime classification from percentile of sigma history
        if len(sigma_history) >= 20:
            sigma_arr = np.array(sigma_history[-100:])  # Recent 100 bars
            pctile = float(np.searchsorted(np.sort(sigma_arr), garch_sigma) / len(sigma_arr) * 100)
        else:
            pctile = 50.0

        if pctile < 25:
            vol_regime = 0  # low
        elif pctile < 75:
            vol_regime = 1  # normal
        elif pctile < 95:
            vol_regime = 2  # high
        else:
            vol_regime = 3  # extreme

        # Standardized shock
        last_epsilon = log_returns[-1]
        shock = last_epsilon**2 / sigma2 if sigma2 > 1e-15 else 0.0

        # Save state for incremental
        self._state = {
            "prev_sigma2": sigma2,
            "prev_close": float(close[-1]),
            "sigma_history": list(sigma_history[-100:]),
            "realized_returns": list(realized_returns),
        }

        return {
            "garch_sigma": float(garch_sigma),
            "garch_vol_ratio": float(vol_ratio),
            "garch_vol_regime": vol_regime,
            "garch_shock": float(shock),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        c = float(row["close"])
        s = self._state

        epsilon = math.log(c / s["prev_close"]) if s["prev_close"] > 0 else 0.0
        sigma2 = self.omega + self.alpha * epsilon**2 + self.beta * s["prev_sigma2"]
        garch_sigma = math.sqrt(sigma2)

        realized_returns = deque(s["realized_returns"], maxlen=20)
        realized_returns.append(epsilon)
        realized_vol = (
            float(np.std(list(realized_returns))) if len(realized_returns) >= 2 else garch_sigma
        )

        vol_ratio = garch_sigma / realized_vol if realized_vol > 1e-10 else 1.0

        sigma_history = s["sigma_history"][-99:] + [garch_sigma]
        sigma_arr = np.array(sigma_history)
        pctile = float(np.searchsorted(np.sort(sigma_arr), garch_sigma) / len(sigma_arr) * 100)

        if pctile < 25:
            vol_regime = 0
        elif pctile < 75:
            vol_regime = 1
        elif pctile < 95:
            vol_regime = 2
        else:
            vol_regime = 3

        shock = epsilon**2 / sigma2 if sigma2 > 1e-15 else 0.0

        self._state = {
            "prev_sigma2": sigma2,
            "prev_close": c,
            "sigma_history": sigma_history,
            "realized_returns": list(realized_returns),
        }

        return {
            "garch_sigma": float(garch_sigma),
            "garch_vol_ratio": float(vol_ratio),
            "garch_vol_regime": vol_regime,
            "garch_shock": float(shock),
        }


plugin = GARCHVolatilityPlugin()
