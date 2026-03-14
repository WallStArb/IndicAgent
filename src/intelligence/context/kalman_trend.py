from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..plugins import InputSpec

_CONFIG_PATH = Path("config/kalman_parameters.json")

# Scale factor for converting garch_sigma (log-return units) to price-unit R.
# garch_sigma is typically 0.001–0.02; squaring and scaling maps to R range 0.1–40.
_GARCH_R_SCALE = 10_000.0


def _load_parameters() -> dict[str, float]:
    """Load Q/R from JSON if available, otherwise use defaults."""
    if _CONFIG_PATH.exists():
        import json

        with open(_CONFIG_PATH) as f:
            data = json.load(f)
        return {
            "Q": float(data.get("Q", 0.5)),
            "R": float(data.get("R", 2.0)),
        }
    return {"Q": 0.5, "R": 2.0}


@dataclass
class KalmanTrendPlugin:
    """1D Kalman filter (local level model) for trend estimation.

    Produces a filtered 'fair value' price and standardized deviation signal.

    State equation:  x(t) = x(t-1) + w(t),  w ~ N(0, Q)
    Observation:     z(t) = x(t) + v(t),     v ~ N(0, R)

    Predict:
        x_pred = x_est
        P_pred = P_est + Q
    Update:
        K      = P_pred / (P_pred + R)
        x_est  = x_pred + K * (close - x_pred)
        P_est  = (1 - K) * P_pred
    """

    name: str = "ctx_KalmanTrend"
    outputs: set[str] = frozenset(
        {
            "kalman_trend",
            "kalman_slope",
            "kalman_price_position",
            "kalman_uncertainty",
            "kalman_upper",
            "kalman_lower",
            "kalman_gain",
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"context", "trend"})
    inputs: list[InputSpec] = field(
        default_factory=lambda: [InputSpec(symbol=".*", timeframe="1m", lookback=200)]
    )
    use_garch_adaptive: bool = False
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        params = _load_parameters()
        self._Q: float = params["Q"]
        self._R_fixed: float = params["R"]

    def _get_R(self, features: dict[str, Any]) -> float:
        """Return measurement noise R, optionally GARCH-adapted."""
        if self.use_garch_adaptive:
            garch_sigma = features.get("garch_sigma")
            if garch_sigma and float(garch_sigma) > 0:
                R_adaptive = (float(garch_sigma) * _GARCH_R_SCALE) ** 2
                return max(0.1, R_adaptive)
        return self._R_fixed

    def _run_filter(
        self,
        closes: np.ndarray,
        R: float,
    ) -> tuple[list[float], list[float], list[float]]:
        """Run Kalman recursion. Returns (x_est_history, P_est_history, K_history)."""
        Q = self._Q
        x_est = float(closes[0])
        P_est = R  # initialize uncertainty = measurement noise

        x_history: list[float] = []
        P_history: list[float] = []
        K_history: list[float] = []

        for c in closes:
            # Predict
            x_pred = x_est
            P_pred = P_est + Q
            # Update
            K = P_pred / (P_pred + R)
            x_est = x_pred + K * (float(c) - x_pred)
            P_est = (1.0 - K) * P_pred

            x_history.append(x_est)
            P_history.append(P_est)
            K_history.append(K)

        return x_history, P_history, K_history

    def _build_result(
        self,
        close: float,
        x_est: float,
        P_est: float,
        K: float,
        trend_history: list[float],
    ) -> dict[str, Any]:
        """Compute all 7 outputs from final Kalman state."""
        uncertainty_band = 2.0 * math.sqrt(max(P_est, 0.0))

        # Slope: trend[t] - trend[t-5] (use available history)
        if len(trend_history) >= 6:
            slope = trend_history[-1] - trend_history[-6]
        elif len(trend_history) >= 2:
            slope = trend_history[-1] - trend_history[0]
        else:
            slope = 0.0

        # Standardized price deviation
        sqrt_P = math.sqrt(max(P_est, 1e-15))
        price_position = (close - x_est) / sqrt_P

        return {
            "kalman_trend": float(x_est),
            "kalman_slope": float(slope),
            "kalman_price_position": float(price_position),
            "kalman_uncertainty": float(P_est),
            "kalman_upper": float(x_est + uncertainty_band),
            "kalman_lower": float(x_est - uncertainty_band),
            "kalman_gain": float(K),
        }

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features", {})
        R = self._get_R(features)
        closes = df["close"].to_numpy(dtype=float)

        x_history, P_history, K_history = self._run_filter(closes, R)

        trend_history = x_history[-6:]  # keep last 6 for slope calc
        x_est = x_history[-1]
        P_est = P_history[-1]
        K = K_history[-1]

        # Save state for incremental updates
        self._state = {
            "x_est": x_est,
            "P_est": P_est,
            "trend_history": trend_history,
            "R": R,
        }

        return self._build_result(float(closes[-1]), x_est, P_est, K, trend_history)

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)

        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        close = float(df.iloc[-1]["close"])
        features = windows.get("features", {})
        R = self._get_R(features) if self.use_garch_adaptive else self._state["R"]
        Q = self._Q

        x_est = self._state["x_est"]
        P_est = self._state["P_est"]
        trend_history: list[float] = list(self._state["trend_history"])

        # Predict + update
        P_pred = P_est + Q
        K = P_pred / (P_pred + R)
        x_est = x_est + K * (close - x_est)
        P_est = (1.0 - K) * P_pred

        trend_history.append(x_est)
        if len(trend_history) > 6:
            trend_history = trend_history[-6:]

        self._state = {
            "x_est": x_est,
            "P_est": P_est,
            "trend_history": trend_history,
            "R": R,
        }

        return self._build_result(close, x_est, P_est, K, trend_history)


plugin = KalmanTrendPlugin()
