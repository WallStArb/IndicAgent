from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog

from ..plugins import InputSpec

logger = structlog.get_logger(__name__)

# Default parameters — sensible starting points for 1m futures bars.
# Override via config/hmm_parameters.json if trained on your data.

_DEFAULT_TRANSITION = np.array(
    [
        [0.95, 0.025, 0.025],  # Ranging stays ranging 95%
        [0.03, 0.94, 0.03],  # Trending-up stays 94%
        [0.03, 0.03, 0.94],  # Trending-down stays 94%
    ]
)

_DEFAULT_MEANS = np.array(
    [
        [0.0, 0.005, 0.0, 0.3, 0.0],  # Ranging
        [0.001, 0.008, 0.3, 0.5, 0.2],  # Trending up
        [-0.001, 0.012, -0.3, 0.5, -0.2],  # Trending down
    ]
)

_DEFAULT_VARIANCES = np.array(
    [
        [0.0001, 0.001, 0.04, 0.04, 0.04],  # Ranging: tight
        [0.0002, 0.002, 0.06, 0.06, 0.06],  # Up: moderate
        [0.0003, 0.003, 0.06, 0.06, 0.06],  # Down: wider
    ]
)

_CONFIG_PATH = Path("config/hmm_parameters.json")


def _load_parameters() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load parameters from JSON if available, otherwise use defaults."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            data = json.load(f)
        return (
            np.array(data["transition_matrix"], dtype=float),
            np.array(data["emission_means"], dtype=float),
            np.array(data["emission_variances"], dtype=float),
        )
    return _DEFAULT_TRANSITION.copy(), _DEFAULT_MEANS.copy(), _DEFAULT_VARIANCES.copy()


def _diag_gaussian_log_prob(x: np.ndarray, means: np.ndarray, variances: np.ndarray) -> np.ndarray:
    """Log probability of x under each of K diagonal Gaussians.

    Args:
        x: observation vector (D,)
        means: (K, D) mean vectors
        variances: (K, D) variance vectors (diagonal covariance)

    Returns:
        (K,) log probabilities
    """
    D = len(x)
    diff = x - means  # (K, D)
    log_probs = -0.5 * np.sum(diff * diff / variances, axis=1)
    log_probs -= 0.5 * np.sum(np.log(variances), axis=1)
    log_probs -= 0.5 * D * math.log(2 * math.pi)
    return log_probs


@dataclass
class HMMRegimePlugin:
    """Hidden Markov Model regime classifier.

    Classifies market into 3 regimes (ranging/trending-up/trending-down)
    using multivariate Gaussian emissions on 5 features. Runs the forward
    algorithm incrementally per bar.
    """

    name: str = "smc_HMMRegime"
    outputs: frozenset[str] = frozenset(
        {
            "hmm_regime",
            "hmm_regime_prob",
            "hmm_prob_ranging",
            "hmm_prob_trending_up",
            "hmm_prob_trending_down",
            "hmm_regime_duration",
            "hmm_n_dims",
            "hmm_warmed_up",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    vol_window: int = 20  # Rolling window for realized vol
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._A, self._means, self._variances = _load_parameters()
        self._K = self._A.shape[0]  # Number of states (3)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        # Compute log returns
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = close[1:] / close[:-1]
            ratios = np.where(ratios > 0, ratios, 1e-10)
            returns = np.log(ratios)

        if len(returns) < self.vol_window:
            return {}

        # Determine feature dimensions
        features = frames.get("features")
        n_dims = self._resolve_dims(features)

        # Initialize state
        self._reset_state()
        self._state["n_dims"] = n_dims

        # Process all bars through forward algorithm
        for i in range(len(returns)):
            self._state["return_buffer"].append(returns[i])
            obs = self._build_observation(
                returns[i],
                list(self._state["return_buffer"]),
                features,
                n_dims,
            )
            self._forward_step(obs, n_dims)

        self._state["prev_close"] = float(close[-1])

        return self._build_output()

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state or "alpha" not in self._state:
            return self.compute_full(windows)

        df = windows.get("main")
        if df is None or len(df) < 2:
            return self.compute_full(windows)

        close = df["close"].to_numpy(dtype=float)
        current_close = float(close[-1])
        prev_close = self._state.get("prev_close", current_close)

        if prev_close <= 0 or current_close <= 0:
            return self.compute_full(windows)

        ret = math.log(current_close / prev_close)
        self._state["return_buffer"].append(ret)

        features = windows.get("features")
        n_dims = self._resolve_dims(features)
        self._state["n_dims"] = n_dims
        buf = list(self._state["return_buffer"])
        obs = self._build_observation(ret, buf, features, n_dims)
        self._forward_step(obs, n_dims)

        self._state["prev_close"] = current_close

        return self._build_output()

    def _resolve_dims(self, features: Any) -> int:
        """Determine how many emission dimensions to use."""
        if not isinstance(features, dict):
            logger.warning("hmm_fallback_2d_no_features")
            return 2  # Fallback: log return + realized vol only
        rsi = features.get("rsi_14")
        adx = features.get("adx_14")
        atr = features.get("atr_14")
        macd_hist = features.get("macd_histogram_12_26_9")
        if rsi is not None and adx is not None and atr is not None and macd_hist is not None:
            return 5
        missing = [
            name
            for name, val in [
                ("rsi_14", rsi),
                ("adx_14", adx),
                ("atr_14", atr),
                ("macd_histogram_12_26_9", macd_hist),
            ]
            if val is None
        ]
        logger.warning("hmm_fallback_2d", missing_fields=missing)
        return 2

    def _build_observation(
        self,
        log_return: float,
        return_window: list | np.ndarray,
        features: Any,
        n_dims: int,
    ) -> np.ndarray:
        """Build the observation vector (2D or 5D)."""
        realized_vol = float(np.std(return_window)) if len(return_window) >= 2 else 0.005
        obs = np.array([log_return, realized_vol])

        if n_dims == 5 and isinstance(features, dict):
            rsi_norm = (float(features["rsi_14"]) - 50.0) / 50.0
            adx_norm = float(features["adx_14"]) / 50.0
            atr = float(features["atr_14"])
            macd_hist = float(features["macd_histogram_12_26_9"])
            macd_norm = macd_hist / atr if atr > 0 else 0.0
            obs = np.array([log_return, realized_vol, rsi_norm, adx_norm, macd_norm])

        return obs

    def _forward_step(self, obs: np.ndarray, n_dims: int) -> None:
        """One step of the forward algorithm."""
        alpha = self._state["alpha"]
        A = self._A

        # Slice parameters to match observation dimensionality
        means = self._means[:, :n_dims]
        variances = self._variances[:, :n_dims]

        # Emission log-probabilities
        log_emit = _diag_gaussian_log_prob(obs, means, variances)

        # Forward update in log space for numerical stability
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_alpha_new = np.zeros(self._K)
        for k in range(self._K):
            log_trans = log_alpha + np.log(np.maximum(A[:, k], 1e-300))
            max_lt = np.max(log_trans)
            log_alpha_new[k] = max_lt + math.log(np.sum(np.exp(log_trans - max_lt)))
        log_alpha_new += log_emit

        # Normalize in log space
        max_la = np.max(log_alpha_new)
        alpha_new = np.exp(log_alpha_new - max_la)
        total = np.sum(alpha_new)
        if total > 0:
            alpha_new /= total

        # Track regime changes
        new_regime = int(np.argmax(alpha_new))
        prev_regime = self._state["prev_regime"]
        if new_regime == prev_regime:
            self._state["regime_duration"] += 1
        else:
            self._state["regime_duration"] = 1
            self._state["prev_regime"] = new_regime

        self._state["alpha"] = alpha_new
        self._state["bars_processed"] = self._state.get("bars_processed", 0) + 1

    def _reset_state(self) -> None:
        """Initialize forward algorithm state."""
        self._state = {
            "alpha": np.full(self._K, 1.0 / self._K),  # Uniform prior
            "prev_close": 0.0,
            "return_buffer": deque(maxlen=self.vol_window),
            "prev_regime": 0,
            "regime_duration": 1,
            "bars_processed": 0,
            "n_dims": 2,
        }

    def _build_output(self) -> dict[str, Any]:
        """Build output dict from current state."""
        alpha = self._state["alpha"]
        regime = int(np.argmax(alpha))
        bars_processed = self._state.get("bars_processed", 0)
        warmed_up = bars_processed >= self.min_lookback
        regime_prob = round(float(alpha[regime]), 6)
        return {
            "hmm_regime": float(regime),
            "hmm_regime_prob": regime_prob if warmed_up else 0.0,
            "hmm_prob_ranging": round(float(alpha[0]), 6) if warmed_up else 0.0,
            "hmm_prob_trending_up": round(float(alpha[1]), 6) if warmed_up else 0.0,
            "hmm_prob_trending_down": round(float(alpha[2]), 6) if warmed_up else 0.0,
            "hmm_regime_duration": float(self._state["regime_duration"]),
            "hmm_n_dims": self._state.get("n_dims", 2),
            "hmm_warmed_up": warmed_up,
        }


plugin = HMMRegimePlugin()
