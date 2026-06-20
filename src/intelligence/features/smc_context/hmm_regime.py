# Incremental cost: O(K^2) per bar where K = number of HMM states (default 3).
# The _forward_step() runs the forward algorithm: K matrix-vector ops on the
# K-state alpha vector, each requiring K multiplications. With K=3 this is 9
# multiplications per bar -- bounded by algorithm, not by a bug. The p95
# latency of 23-35ms is due to NumPy overhead on small arrays, not algorithmic
# complexity. Reduction options: Cython/Numba for the inner loop, or increase
# thread pool workers so concurrent HMM instances overlap. Do NOT force O(1).
"""HMMRegime plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full HMM forward pass computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract forward algorithm state
"""

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

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin

logger = structlog.get_logger(__name__)

# Default parameters -- sensible starting points for 1m futures bars.
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

# TF-adaptive window sizes for hmm_regime_velocity computation.
# Shorter windows for higher-frequency TFs to stay responsive.
VELOCITY_WINDOW_BY_TF: dict[str, int] = {
    "1m": 5,
    "5m": 5,
    "15m": 4,
    "1h": 3,
}


def _load_parameters_from_path(
    config_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load parameters from a specific JSON path, falling back to defaults."""
    if config_path.exists():
        with open(config_path) as f:
            data = json.load(f)
        return (
            np.array(data["transition_matrix"], dtype=float),
            np.array(data["emission_means"], dtype=float),
            np.array(data["emission_variances"], dtype=float),
        )
    return _DEFAULT_TRANSITION.copy(), _DEFAULT_MEANS.copy(), _DEFAULT_VARIANCES.copy()


def _load_parameters() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load parameters from JSON if available, otherwise use defaults."""
    return _load_parameters_from_path(_CONFIG_PATH)


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
class HMMRegimePlugin(IncrementalMixin):
    """Hidden Markov Model regime classifier.

    Classifies market into 3 regimes (ranging/trending-up/trending-down)
    using multivariate Gaussian emissions on 5 features. Runs the forward
    algorithm incrementally per bar.

    Multi-TF support: pass ``timeframe`` and ``lookback`` to create TF-specific
    instances. Each instance loads ``config/hmm_parameters_{tf}.json`` if
    present, falling back to the base ``config/hmm_parameters.json``.
    """

    # Init params -- drive name, inputs, and parameter file resolution.
    timeframe: str = "1m"
    lookback: int = 200

    # Derived fields -- set in __post_init__, not passed to __init__.
    name: str = field(init=False)
    outputs: frozenset[str] = field(init=False)
    inputs: tuple[InputSpec, ...] = field(init=False)

    # Static fields
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    vol_window: int = 20  # Rolling window for realized vol

    def __post_init__(self) -> None:
        self.name = f"smc_HMMRegime_{self.timeframe}"
        self.inputs = (InputSpec(symbol=".*", timeframe=self.timeframe, lookback=self.lookback),)
        self.outputs = frozenset(
            {
                "hmm_regime",
                "hmm_regime_prob",
                "hmm_prob_ranging",
                "hmm_prob_trending_up",
                "hmm_prob_trending_down",
                "hmm_probability",
                "hmm_regime_duration",
                "hmm_n_dims",
                "hmm_warmed_up",
                "hmm_regime_entropy",
                "hmm_regime_velocity",
            }
        )
        self._A, self._means, self._variances = self._load_tf_parameters()
        self._K = self._A.shape[0]  # Number of states (3)

    def _load_tf_parameters(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Load parameters using TF-suffixed path with fallback to base file."""
        tf_path = Path(f"config/hmm_parameters_{self.timeframe}.json")
        base_path = _CONFIG_PATH
        A, means, variances = (
            _load_parameters_from_path(tf_path)
            if tf_path.exists()
            else _load_parameters_from_path(base_path)
        )
        n_dims = means.shape[1]
        if n_dims not in (2, 5):
            logger.warning(
                "hmm_params_unexpected_dims",
                plugin=f"smc_HMMRegime_{self.timeframe}",
                n_dims=n_dims,
                expected="2 or 5",
            )
        if n_dims == 2:
            logger.warning(
                "hmm_params_2d_loaded",
                plugin=f"smc_HMMRegime_{self.timeframe}",
                action="running in 2D fallback mode -- retrain to upgrade to 5D",
            )
        return A, means, variances

    def reload_parameters(self) -> None:
        """Hot-reload HMM parameters from disk (called by SIGUSR1 handler).

        Idempotent -- safe to call multiple times. Replaces transition matrix,
        emission means, and variances. Does NOT reset forward algorithm state.
        """
        self._A, self._means, self._variances = self._load_tf_parameters()
        self._K = self._A.shape[0]

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full HMM forward pass computation. Returns outputs only (no _state)."""
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
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        n_dims = self._resolve_dims(features)

        # Initialize state and process all bars through forward algorithm
        hmm_state = self._make_initial_state(n_dims)

        for i in range(len(returns)):
            hmm_state["return_buffer"].append(returns[i])
            obs = self._build_observation(
                returns[i],
                list(hmm_state["return_buffer"]),
                features,
                n_dims,
            )
            self._forward_step(obs, n_dims, hmm_state)

        hmm_state["prev_close"] = float(close[-1])

        return self._build_output(hmm_state)

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract forward algorithm state for incremental seeding."""
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = close[1:] / close[:-1]
            ratios = np.where(ratios > 0, ratios, 1e-10)
            returns = np.log(ratios)

        if len(returns) < self.vol_window:
            return {}

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        n_dims = self._resolve_dims(features)

        hmm_state = self._make_initial_state(n_dims)

        for i in range(len(returns)):
            hmm_state["return_buffer"].append(returns[i])
            obs = self._build_observation(
                returns[i],
                list(hmm_state["return_buffer"]),
                features,
                n_dims,
            )
            self._forward_step(obs, n_dims, hmm_state)

        hmm_state["prev_close"] = float(close[-1])

        return hmm_state

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental HMM update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 2:
            return {}

        close = df["close"].to_numpy(dtype=float)
        current_close = float(close[-1])
        prev_close = state.get("prev_close", current_close)

        if prev_close <= 0 or current_close <= 0:
            return {}

        ret = math.log(current_close / prev_close)
        state["return_buffer"].append(ret)

        features = {
            **(windows.get("i1") or {}),
            **(windows.get("i2") or {}),
            **(windows.get("i3") or {}),
            **(windows.get("i4") or {}),
            **(windows.get("i5") or {}),
            **(windows.get("smc") or {}),
        }
        n_dims = self._resolve_dims(features)
        state["n_dims"] = n_dims
        buf = list(state["return_buffer"])
        obs = self._build_observation(ret, buf, features, n_dims)
        self._forward_step(obs, n_dims, state)

        state["prev_close"] = current_close

        return self._build_output(state)

    def _make_initial_state(self, n_dims: int) -> dict:
        """Create a fresh HMM forward algorithm state dict."""
        velocity_window = VELOCITY_WINDOW_BY_TF.get(self.timeframe, 5)
        return {
            "alpha": np.full(self._K, 1.0 / self._K),  # Uniform prior
            "prev_close": 0.0,
            "return_buffer": deque(maxlen=self.vol_window),
            "prev_regime": 0,
            "regime_duration": 1,
            "bars_processed": 0,
            "n_dims": n_dims,
            "prob_history": deque(maxlen=velocity_window),
        }

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

    def _forward_step(self, obs: np.ndarray, n_dims: int, state: dict) -> None:
        """One step of the forward algorithm."""
        alpha = state["alpha"]
        A = self._A

        # Clamp n_dims to param dimensionality -- loaded params may have been trained
        # in 2D mode (insufficient indicator coverage at training time) while runtime
        # now resolves 5D. Truncate obs rather than broadcast-fail.
        # _load_tf_parameters() warns at startup when this mismatch exists.
        param_dims = self._means.shape[1]
        if n_dims > param_dims:
            obs = obs[:param_dims]
            n_dims = param_dims

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
        prev_regime = state["prev_regime"]
        if new_regime == prev_regime:
            state["regime_duration"] += 1
        else:
            state["regime_duration"] = 1
            state["prev_regime"] = new_regime

        state["alpha"] = alpha_new
        state["bars_processed"] = state.get("bars_processed", 0) + 1

    def _build_output(self, state: dict) -> dict[str, Any]:
        """Build output dict from current state."""
        alpha = state["alpha"]
        regime = int(np.argmax(alpha))
        bars_processed = state.get("bars_processed", 0)
        warmed_up = bars_processed >= self.min_lookback
        regime_prob = round(float(alpha[regime]), 6)

        # Shannon entropy across 3 state probabilities -- high = regime transition window.
        hmm_regime_entropy = float(-np.sum(alpha * np.log2(alpha + 1e-10)))

        # Velocity: rate of change of dominant-state probability over the history window.
        prob_history = state.get("prob_history")
        if prob_history is None:
            # Lazily initialize for instances whose state was restored from checkpoint
            # without the prob_history key (backward compat).
            velocity_window = VELOCITY_WINDOW_BY_TF.get(self.timeframe, 5)
            prob_history = deque(maxlen=velocity_window)
            state["prob_history"] = prob_history
        prob_history.append(float(regime_prob))
        if len(prob_history) >= 2:
            hmm_regime_velocity = float(
                (prob_history[-1] - prob_history[0]) / max(1, len(prob_history) - 1)
            )
        else:
            hmm_regime_velocity = 0.0

        return {
            "hmm_regime": float(regime),
            "hmm_regime_prob": regime_prob if warmed_up else 0.0,
            "hmm_prob_ranging": round(float(alpha[0]), 6) if warmed_up else 0.0,
            "hmm_prob_trending_up": round(float(alpha[1]), 6) if warmed_up else 0.0,
            "hmm_prob_trending_down": round(float(alpha[2]), 6) if warmed_up else 0.0,
            "hmm_probability": round(float(alpha[1]) + float(alpha[2]), 6) if warmed_up else 0.0,
            "hmm_regime_duration": float(state["regime_duration"]),
            "hmm_n_dims": state.get("n_dims", 2),
            "hmm_warmed_up": warmed_up,
            "hmm_regime_entropy": round(hmm_regime_entropy, 6) if warmed_up else None,
            "hmm_regime_velocity": round(hmm_regime_velocity, 6) if warmed_up else None,
        }


plugin = HMMRegimePlugin(timeframe="1m", lookback=200)
