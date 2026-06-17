# Incremental cost: O(R) per bar where R = max_run_length (default 200).
# The _update() forward pass allocates R-length NumPy arrays each call --
# this is bounded by algorithm, not by a bug. BOCPD cannot be reduced to O(1)
# without approximation (particle filter, pruning). The p95 latency of ~77ms
# is expected for R=200 on 1m bars. Reduction options: lower max_run_length,
# or use BOCPD only on selected timeframes. Do NOT force O(1) -- document here.
"""BOCPDChangePoint plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full BOCPD computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract run-length distribution state
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


def _student_t_pdf(x: np.ndarray, df: np.ndarray, loc: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Vectorized Student-t PDF without scipy.

    f(x; df, loc, scale) =
        Γ((df+1)/2) / (√(df·π) · Γ(df/2) · scale)
        · (1 + ((x-loc)/scale)² / df)^(-(df+1)/2)
    """
    z = (x - loc) / scale
    # Use log-gamma for numerical stability
    log_coeff = np.array([math.lgamma(0.5 * (d + 1)) - math.lgamma(0.5 * d) for d in df])
    log_norm = -0.5 * np.log(df * np.pi) - np.log(scale)
    log_body = -0.5 * (df + 1) * np.log(1 + z * z / df)
    return np.exp(log_coeff + log_norm + log_body)


@dataclass
class BOCPDChangePointPlugin(IncrementalMixin):
    """Bayesian Online Change Point Detection (Adams & MacKay 2007).

    Detects the moment market regime changes using log returns.
    Maintains a run length distribution updated each bar.
    Feature confirmation from I1 outputs adjusts raw probability.
    """

    name: str = "smc_BOCPDChangePoint"
    outputs: frozenset[str] = frozenset(
        {
            "cp_probability",
            "cp_raw_probability",
            "cp_run_length",
            "cp_confirmation",
            "cp_detected",
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=200),)
    hazard_lambda: int = 100  # Expected regime duration in bars
    max_run_length: int = 200  # Truncation cap
    cp_threshold: float = 0.5  # Detection threshold
    # Student-t conjugate prior hyperparameters
    mu0: float = 0.0
    kappa0: float = 1.0
    alpha0: float = 0.1
    beta0: float = 0.01

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full BOCPD computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        # Compute log returns
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = close[1:] / close[:-1]
            ratios = np.where(ratios > 0, ratios, 1e-10)
            returns = np.log(ratios)

        if len(returns) < 2:
            return {}

        # Run BOCPD on all returns
        bocpd_state = self._make_initial_state()
        for x in returns:
            self._update(float(x), bocpd_state)

        bocpd_state["prev_close"] = float(close[-1])

        raw_prob = bocpd_state["cp_prob"]
        run_length = int(np.argmax(bocpd_state["run_length_probs"]))

        confirmation = self._compute_confirmation(df, frames)
        adjusted = raw_prob * (0.5 + 0.5 * confirmation)

        return {
            "cp_probability": round(float(adjusted), 6),
            "cp_raw_probability": round(float(raw_prob), 6),
            "cp_run_length": float(run_length),
            "cp_confirmation": round(float(confirmation), 4),
            "cp_detected": 1.0 if adjusted > self.cp_threshold else 0.0,
        }

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract run-length distribution state for incremental seeding.

        Deep-copies numpy arrays so they are independent from this call's state.
        """
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = close[1:] / close[:-1]
            ratios = np.where(ratios > 0, ratios, 1e-10)
            returns = np.log(ratios)

        if len(returns) < 2:
            return {}

        bocpd_state = self._make_initial_state()
        for x in returns:
            self._update(float(x), bocpd_state)

        bocpd_state["prev_close"] = float(close[-1])

        # Deep copy: numpy arrays in state must be independent from future calls
        return copy.deepcopy(bocpd_state)

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental BOCPD update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 2:
            return {}

        close = df["close"].to_numpy(dtype=float)
        current_close = float(close[-1])
        prev_close = state.get("prev_close", current_close)

        if prev_close <= 0 or current_close <= 0:
            return {}

        x = math.log(current_close / prev_close)
        self._update(x, state)

        raw_prob = state["cp_prob"]
        run_length = int(np.argmax(state["run_length_probs"]))
        state["prev_close"] = current_close

        confirmation = self._compute_confirmation(df, windows)
        adjusted = raw_prob * (0.5 + 0.5 * confirmation)

        return {
            "cp_probability": round(float(adjusted), 6),
            "cp_raw_probability": round(float(raw_prob), 6),
            "cp_run_length": float(run_length),
            "cp_confirmation": round(float(confirmation), 4),
            "cp_detected": 1.0 if adjusted > self.cp_threshold else 0.0,
        }

    def _make_initial_state(self) -> dict:
        """Create a fresh BOCPD state dict."""
        R = self.max_run_length
        state: dict = {
            "run_length_probs": np.zeros(R),
            "mu": np.full(R, self.mu0),
            "kappa": np.full(R, self.kappa0),
            "alpha": np.full(R, self.alpha0),
            "beta": np.full(R, self.beta0),
            "cp_prob": 0.0,
        }
        state["run_length_probs"][0] = 1.0
        return state

    def _update(self, x: float, state: dict) -> None:
        """Process one observation through the BOCPD forward pass."""
        R = self.max_run_length
        s = state
        rl = s["run_length_probs"]
        mu = s["mu"]
        kappa = s["kappa"]
        alpha = s["alpha"]
        beta = s["beta"]
        hazard = 1.0 / self.hazard_lambda

        # Predictive probabilities via Student-t
        df_param = 2 * alpha
        scale = np.sqrt(beta * (kappa + 1) / (alpha * kappa))
        scale = np.where(scale > 0, scale, 1e-10)
        df_param = np.where(df_param > 0, df_param, 1e-10)

        pred_probs = _student_t_pdf(np.full(R, x), df_param, mu, scale)

        # Growth: P(r+1) = P(x|r) * P(r) * (1 - hazard)
        growth = rl * pred_probs * (1 - hazard)

        # Change point: P(r=0) = sum of P(x|r) * P(r) * hazard
        cp_mass = float(np.sum(rl * pred_probs * hazard))

        # Shift and truncate
        new_rl = np.zeros(R)
        new_rl[1:] = growth[: R - 1]
        new_rl[0] = cp_mass

        # Normalize
        total = np.sum(new_rl)
        if total > 0:
            new_rl /= total

        # Update sufficient statistics for continued runs (shift r -> r+1)
        new_mu = np.full(R, self.mu0)
        new_kappa = np.full(R, self.kappa0)
        new_alpha = np.full(R, self.alpha0)
        new_beta = np.full(R, self.beta0)

        old_mu = mu[: R - 1]
        old_kappa = kappa[: R - 1]
        old_alpha = alpha[: R - 1]
        old_beta = beta[: R - 1]

        new_kappa[1:] = old_kappa + 1
        new_mu[1:] = (old_kappa * old_mu + x) / new_kappa[1:]
        new_alpha[1:] = old_alpha + 0.5
        new_beta[1:] = old_beta + old_kappa * (x - old_mu) ** 2 / (2 * new_kappa[1:])

        s["run_length_probs"] = new_rl
        s["mu"] = new_mu
        s["kappa"] = new_kappa
        s["alpha"] = new_alpha
        s["beta"] = new_beta
        s["cp_prob"] = float(new_rl[0])

    def _compute_confirmation(self, df: pd.DataFrame, frames: dict[str, Any]) -> float:
        """Score feature confirmation from I1 outputs (0-1)."""
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        if not isinstance(features, dict):
            return 0.5  # No features available -- neutral

        confirmation = 0.0
        close = df["close"].to_numpy(dtype=float)
        n = len(close)

        # 1. Volatility regime shift
        vol_pct = features.get("vol_percentile")
        if vol_pct is not None:
            if float(vol_pct) > 0.75 or float(vol_pct) < 0.25:
                confirmation += 0.25

        # 2. RSI near 50 midline (transition zone)
        rsi = features.get("rsi_14")
        if rsi is not None:
            if 45 <= float(rsi) <= 55:
                confirmation += 0.25

        # 3. Volume spike
        if "volume" in df.columns and n > 20:
            vol = df["volume"].to_numpy(dtype=float)
            avg_vol = float(np.mean(vol[-21:-1]))
            if avg_vol > 0 and vol[-1] > 2 * avg_vol:
                confirmation += 0.25

        # 4. Price crossed SMA-20
        if n >= 21:
            sma20 = float(np.mean(close[-20:]))
            prev_sma20 = float(np.mean(close[-21:-1]))
            if (close[-2] < prev_sma20 and close[-1] > sma20) or (
                close[-2] > prev_sma20 and close[-1] < sma20
            ):
                confirmation += 0.25

        return min(1.0, confirmation)


plugin = BOCPDChangePointPlugin()
