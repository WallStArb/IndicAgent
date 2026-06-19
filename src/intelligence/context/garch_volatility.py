"""GARCH volatility plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full GARCH(1,1) computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract sigma2/realized vol state
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..plugins.mixins import IncrementalMixin


@dataclass
class GARCHVolatilityPlugin(IncrementalMixin):
    """GARCH(1,1) conditional volatility forecast.

    Forecasts next-bar volatility. Forward-looking complement to the
    backward-looking VolatilityRegime plugin.

    sigma2_t = omega + alpha * epsilon_{t-1}^2 + beta * sigma2_{t-1}
    """

    name: str = "ctx_GARCHVolatility"
    outputs: frozenset[str] = frozenset(
        {"garch_sigma", "garch_vol_ratio", "garch_vol_regime", "garch_shock"}
    )
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"context", "volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=200),)
    omega: float = 0.00001
    alpha: float = 0.10
    beta: float = 0.85
    _config_service: Any = field(default=None, compare=False, repr=False)

    def _get_params(self) -> tuple[float, float, float]:
        """Return (omega, alpha, beta), reading from APR if config_service is wired."""
        cfg = self._config_service
        if cfg is None:
            return self.omega, self.alpha, self.beta
        return (
            float(cfg.get_sync("feature.garch.omega", self.omega)),
            float(cfg.get_sync("feature.garch.alpha", self.alpha)),
            float(cfg.get_sync("feature.garch.beta", self.beta)),
        )

    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Full GARCH(1,1) computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        omega, alpha, beta = self._get_params()
        close = df["close"].to_numpy(dtype=float)

        # Log returns
        log_returns = np.log(close[1:] / close[:-1])
        log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)

        # Initialize sigma2 with variance of first 20 returns
        init_window = min(20, len(log_returns))
        sigma2 = float(np.var(log_returns[:init_window]))
        if sigma2 == 0:
            denom = 1 - alpha - beta
            sigma2 = omega / denom if denom > 1e-10 else omega

        # Rolling realized vol (std of last 20 log returns)
        realized_returns: deque[float] = deque(maxlen=20)

        # GARCH recursion -- track sigma2 before last update for unbiased shock
        sigma_history: list[float] = []
        sigma2_prior_last = sigma2
        for i in range(len(log_returns)):
            epsilon = log_returns[i]
            sigma2_prior_last = sigma2
            sigma2 = omega + alpha * epsilon**2 + beta * sigma2
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

        # Standardized shock: use sigma2 BEFORE incorporating last_epsilon (prior, not posterior)
        last_epsilon = log_returns[-1]
        shock = last_epsilon**2 / sigma2_prior_last if sigma2_prior_last > 1e-15 else 0.0

        return {
            "garch_sigma": float(garch_sigma),
            "garch_vol_ratio": float(vol_ratio),
            "garch_vol_regime": vol_regime,
            "garch_shock": float(shock),
        }

    def _seed_state(self, frames: dict[str, Any]) -> dict:
        """Extract sigma2/realized vol state for incremental seeding."""
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        omega, alpha, beta = self._get_params()
        close = df["close"].to_numpy(dtype=float)
        log_returns = np.log(close[1:] / close[:-1])
        log_returns = np.where(np.isfinite(log_returns), log_returns, 0.0)

        init_window = min(20, len(log_returns))
        sigma2 = float(np.var(log_returns[:init_window]))
        if sigma2 == 0:
            denom = 1 - alpha - beta
            sigma2 = omega / denom if denom > 1e-10 else omega

        realized_returns: deque[float] = deque(maxlen=20)
        sigma_history: list[float] = []

        for i in range(len(log_returns)):
            epsilon = log_returns[i]
            sigma2 = omega + alpha * epsilon**2 + beta * sigma2
            sigma_history.append(math.sqrt(sigma2))
            realized_returns.append(epsilon)

        return {
            "prev_sigma2": sigma2,
            "prev_close": float(close[-1]),
            "sigma_history": list(sigma_history[-100:]),
            "realized_returns": list(realized_returns),
        }

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental GARCH update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        c = float(row["close"])

        omega, alpha, beta = self._get_params()
        epsilon = math.log(c / state["prev_close"]) if state["prev_close"] > 0 else 0.0
        sigma2 = omega + alpha * epsilon**2 + beta * state["prev_sigma2"]
        garch_sigma = math.sqrt(sigma2)

        realized_returns = deque(state["realized_returns"], maxlen=20)
        realized_returns.append(epsilon)
        realized_vol = (
            float(np.std(list(realized_returns))) if len(realized_returns) >= 2 else garch_sigma
        )

        vol_ratio = garch_sigma / realized_vol if realized_vol > 1e-10 else 1.0

        sigma_history = state["sigma_history"][-99:] + [garch_sigma]
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

        # Use prev_sigma2 (prior) not sigma2 (posterior) for unbiased shock
        shock = epsilon**2 / state["prev_sigma2"] if state["prev_sigma2"] > 1e-15 else 0.0

        state["prev_sigma2"] = sigma2
        state["prev_close"] = c
        state["sigma_history"] = sigma_history
        state["realized_returns"] = list(realized_returns)

        return {
            "garch_sigma": float(garch_sigma),
            "garch_vol_ratio": float(vol_ratio),
            "garch_vol_regime": vol_regime,
            "garch_shock": float(shock),
        }


plugin = GARCHVolatilityPlugin()
