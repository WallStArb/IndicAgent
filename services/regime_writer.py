#!/usr/bin/env python3
"""Regime Writer — oneshot that populates feature_vectors.regime via causal HMM decoding.

Builds one GaussianHMM model per (symbol, tf) from market_data_ohlcv (log-returns +
ATR-proxy realized vol), decodes causally via forward-filter alpha-pass ONLY, then
batch-UPDATEs feature_vectors.regime with canonical text labels.

CORRECTNESS INVARIANTS:
- Observation matrix from market_data_ohlcv, NOT feature_vectors (no OHLCV columns there).
- Decoding uses forward-filter (alpha-pass only), mirroring hmm_regime.py:_forward_step().
  model.predict() is NOT used — it runs full-sequence Viterbi and leaks future information.
- Each (symbol, tf) gets its own independent HMM fit. No shared model across TFs.
- Regime labels are deterministically mapped by emission mean[:, 0] (log-return dimension):
    K=2: trending_up (high), trending_down (low)
    K=3: trending_up, ranging, trending_down
    K=5: trending_up, transition_up, ranging, transition_down, trending_down
         (BIC-validated K as of Phase 140.5-P2 BIC study 2026-06-26)
  For K>3, hmm_prob_trending_up/down aggregate all bullish/bearish probability mass.

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as backfill_feature_factory.py is — it is a batch labeling tool, not a
real-time daemon. The ring 2 boundary still holds: no async pipeline, no Kafka.

Usage:
    python services/regime_writer.py
    python services/regime_writer.py --symbols SPY TLT
    python services/regime_writer.py --tf 5m 15m
    python services/regime_writer.py --symbols SPY --tf 5m
    python services/regime_writer.py --workers 12 --refit
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import structlog
from hmmlearn.hmm import GaussianHMM
from opentelemetry import trace
from sklearn.preprocessing import StandardScaler

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import bulk_update_by_key as _bulk_update_by_key
from services._batch_utils import load_config_service_sync as _load_config_service_shared
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    REGIME_WRITER_NULL_REGIME_REMAINING,
    REGIME_WRITER_ROWS_UPDATED_TOTAL,
    REGIME_WRITER_RUN_LATENCY_SECONDS,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/regime_writer.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "regime-writer"

# HMM random state loaded from APR at runtime: alpha.hmm.random_state (default 42).
# Changing it invalidates all regime labels in feature_vectors — requires full re-run.

# Default target timeframes (matches backfill_feature_factory.py targets).
_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# Minimum obs rows per (symbol, tf) = n_components * this factor.
# Below this, the fit is meaningless (too few state transitions to estimate A).
_MIN_OBS_FACTOR = 50

# Canonical regime label set — no other values written to DB.
_LABEL_TRENDING_UP = "trending_up"
_LABEL_TRENDING_DOWN = "trending_down"
_LABEL_RANGING = "ranging"
_LABEL_TRANSITION_UP = "transition_up"
_LABEL_TRANSITION_DOWN = "transition_down"

# Labels that count as "bullish" for hmm_prob_trending_up aggregation.
_BULLISH_LABELS = frozenset([_LABEL_TRENDING_UP, _LABEL_TRANSITION_UP])
# Labels that count as "bearish" for hmm_prob_trending_down aggregation.
_BEARISH_LABELS = frozenset([_LABEL_TRENDING_DOWN, _LABEL_TRANSITION_DOWN])


@contextlib.contextmanager
def _noop_span(name, **attrs):
    class _Noop:
        def set_attribute(self, k, v):
            pass

        def set_status(self, *a):
            pass

        def record_exception(self, *a):
            pass

    yield _Noop()


class _NoopTracer:
    """Subprocess-safe tracer stub — OTel spans must not be emitted from workers."""

    def start_as_current_span(self, name, attributes=None):
        return _noop_span(name)


# ---------------------------------------------------------------------------
# Core HMM functions
# ---------------------------------------------------------------------------


def _rolling(arr: np.ndarray, window: int, fn) -> np.ndarray:
    """Apply fn over a sliding window, zero-padding the warm-up prefix."""
    windows = np.lib.stride_tricks.sliding_window_view(arr, window)
    return np.concatenate([np.zeros(window - 1), fn(windows, axis=1)])


def _build_obs_matrix(
    timestamps: list,
    closes: list[float],
    volumes: list[float],
    vol_window: int,
    momentum_window: int,
    vol_of_vol_window: int,
) -> tuple[np.ndarray, list]:
    """Build (n_valid, 5) observation matrix from OHLCV prices and volumes.

    Observation dimensions:
      [0] log_return   = ln(close[t] / close[t-1])
      [1] realized_vol = rolling std of log_returns over vol_window bars
      [2] momentum     = sum(log_returns[-momentum_window:]) / (realized_vol + eps)
                         Directional drift signal, vol-normalized.
      [3] vol_of_vol   = rolling std of realized_vol over vol_of_vol_window bars
                         Regime transition indicator: stable regimes have stable vol.
      [4] rel_volume   = log(volume[t]) - rolling mean(log(volume), vol_window)
                         Volume anomaly relative to recent baseline.

    valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
    All rows before valid_start are discarded (insufficient window history).
    Returns (obs_matrix, valid_timestamps).
    """
    closes_arr = np.array(closes, dtype=float)
    volumes_arr = np.maximum(np.array(volumes, dtype=float), 1.0)  # guard zero volume

    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))
    log_volumes = np.log(volumes_arr[1:])  # aligned to log_returns
    ts_shifted = timestamps[1:]

    if len(log_returns) < max(vol_window, momentum_window, vol_of_vol_window):
        return np.empty((0, 5), dtype=float), []

    realized_vol = _rolling(log_returns, vol_window, np.std)
    mom_raw = _rolling(log_returns, momentum_window, np.sum)
    momentum = mom_raw / np.maximum(realized_vol, 1e-8)
    vol_of_vol = _rolling(realized_vol, vol_of_vol_window, np.std)
    rolling_mean_logvol = _rolling(log_volumes, vol_window, np.mean)
    rel_volume = log_volumes - rolling_mean_logvol

    valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
    obs = np.column_stack(
        [
            log_returns[valid_start:],
            realized_vol[valid_start:],
            momentum[valid_start:],
            vol_of_vol[valid_start:],
            rel_volume[valid_start:],
        ]
    )
    valid_ts = ts_shifted[valid_start:]
    return obs, valid_ts


def _stationary_distribution(A: np.ndarray) -> np.ndarray:
    """Stationary distribution of transition matrix A (left eigenvector for eigenvalue 1).

    Solves π A = π with sum(π) = 1. Falls back to uniform if singular.
    """
    K = A.shape[0]
    M = A.T - np.eye(K)
    M[-1] = 1.0
    rhs = np.zeros(K)
    rhs[-1] = 1.0
    try:
        pi = np.linalg.solve(M, rhs)
        pi = np.maximum(pi, 0.0)
        total = pi.sum()
        return pi / total if total > 0 else np.full(K, 1.0 / K)
    except np.linalg.LinAlgError:
        return np.full(K, 1.0 / K)


def _log_emit_diag(obs: np.ndarray, means: np.ndarray, variances: np.ndarray) -> np.ndarray:
    """Log emission (n, K) for diagonal Gaussian. variances shape (K, d)."""
    var_clipped = np.maximum(variances, 1e-300)
    diff = obs[:, np.newaxis, :] - means[np.newaxis, :, :]  # (n, K, d)
    return (
        -0.5 * np.sum(diff**2 / var_clipped[np.newaxis, :, :], axis=2)
        - 0.5 * np.sum(np.log(2 * np.pi * var_clipped), axis=1)[np.newaxis, :]
    )


def _log_emit_full(obs: np.ndarray, means: np.ndarray, covars: np.ndarray) -> np.ndarray:
    """Log emission (n, K) for full-covariance Gaussian. covars shape (K, d, d).

    Uses Cholesky decomposition for numerical stability. Regularizes with 1e-6 * I
    to guard near-singular covariance matrices (rare but possible on flat TFs).
    Falls back to diagonal on Cholesky failure per state.
    """
    n, d = obs.shape
    K = means.shape[0]
    log_emit = np.zeros((n, K))
    log_2pi_d = d * math.log(2 * math.pi)
    for k in range(K):
        diff = obs - means[k]  # (n, d)
        cov = covars[k] + np.eye(d) * 1e-6
        try:
            L = np.linalg.cholesky(cov)
            log_det = 2.0 * np.sum(np.log(np.maximum(np.diag(L), 1e-300)))
            y = np.linalg.solve(L, diff.T)  # (d, n)
            log_emit[:, k] = -0.5 * (np.sum(y**2, axis=0) + log_det + log_2pi_d)
        except np.linalg.LinAlgError:
            diag_var = np.maximum(np.diag(covars[k]), 1e-300)
            log_emit[:, k] = -0.5 * (
                np.sum(diff**2 / diag_var, axis=1) + np.sum(np.log(2 * math.pi * diag_var))
            )
    return log_emit


def _alpha_pass(
    log_emit: np.ndarray,
    A: np.ndarray,
    pi0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal forward-filter. log_emit shape (n, K). Returns (states, alpha_history).

    Sequential t-loop is required — alpha[t] depends on alpha[t-1] for causality.
    Log emission matrix is precomputed outside for the full series at once.
    """
    n, K = log_emit.shape
    log_A = np.log(np.maximum(A, 1e-300))
    states = np.zeros(n, dtype=int)
    alpha_history = np.zeros((n, K))
    alpha = pi0.copy()

    for t in range(n):
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_trans = log_alpha[:, np.newaxis] + log_A  # (K, K)
        max_lt = log_trans.max(axis=0)
        log_alpha_new = max_lt + np.log(np.sum(np.exp(log_trans - max_lt), axis=0))
        log_alpha_new += log_emit[t]
        max_la = log_alpha_new.max()
        alpha = np.exp(log_alpha_new - max_la)
        total = alpha.sum()
        alpha /= total if total > 0 else 1.0
        states[t] = int(alpha.argmax())
        alpha_history[t] = alpha

    return states, alpha_history


# Backward-compat alias — function was renamed from _causal_decode to _alpha_pass
_causal_decode = _alpha_pass


def _smooth_states(raw_states: np.ndarray, min_hold: int) -> np.ndarray:
    """Minimum holding-period smoother. Requires min_hold consecutive bars of the same
    new state before confirming a transition. Causal — no look-ahead."""
    if min_hold <= 1:
        return raw_states.copy()
    n = len(raw_states)
    smoothed = raw_states.copy()
    current = int(raw_states[0])
    for t in range(1, n):
        if t < min_hold:
            smoothed[t] = current
            continue
        window = raw_states[t - min_hold + 1 : t + 1]
        if np.all(window == raw_states[t]):
            current = int(raw_states[t])
        smoothed[t] = current
    return smoothed


def _check_occupation_gate(
    smoothed_states: np.ndarray,
    n_components: int,
    min_state_occupation: float,
    converged: bool,
) -> tuple[bool, dict[str, Any]]:
    """Guard against degenerate HMM fits before their labels can be written.

    Returns (is_degenerate, diagnostics). is_degenerate=True means the caller must
    skip the write for this cell -- the smoothed label sequence is either empty,
    too short to trust, came from a non-converged fit, or one state's occupation
    fraction collapsed below min_state_occupation (the model degenerated onto too
    few effective states, absorbing almost all bars into one label). Guards run
    in this order BEFORE any division by len(smoothed_states) so empty/short
    input can never divide-by-zero or index out of range.

    Occupation fractions are computed from smoothed_states -- the actual label
    assignments that would be written -- not from the model's stationary
    distribution or any other summary statistic.
    """
    n_obs = len(smoothed_states)
    if n_obs == 0:
        return True, {"reason": "empty_series", "n_obs": 0}
    if n_obs < n_components:
        return True, {
            "reason": "insufficient_obs",
            "n_obs": n_obs,
            "n_components": n_components,
        }
    if not converged:
        return True, {"reason": "not_converged", "n_obs": n_obs}

    occupation = {
        int(k): float(np.count_nonzero(smoothed_states == k)) / n_obs for k in range(n_components)
    }
    min_state = min(occupation, key=occupation.get)
    min_fraction = occupation[min_state]
    if min_fraction < min_state_occupation:
        return True, {
            "reason": "degenerate_occupation",
            "min_state": min_state,
            "min_fraction": min_fraction,
            "occupation": occupation,
        }
    return False, {"reason": None, "occupation": occupation}


def _compute_hmm_churn(labels: list | np.ndarray, churn_window: int) -> np.ndarray:
    """Rolling label-change churn rate over the prior churn_window bars (P2c).

    churn[i] = (# label changes in labels[max(0, i-churn_window+1) : i+1]) /
               min(i+1, churn_window)

    Partial windows (the first churn_window-1 bars) divide by bars-available,
    never by a hardcoded churn_window -- no NaN, no divide-by-zero. The very
    first bar has no predecessor and is defined as zero change (label-change
    rate is undefined, not degenerate, for a single observation).

    Accepts any sequence whose elements support `!=` (regime label strings or
    raw state indices) -- churn is computed on whatever label identity the
    caller passes in.
    """
    n = len(labels)
    if n == 0:
        return np.zeros(0, dtype=float)

    labels_arr = np.asarray(labels, dtype=object)
    changes = np.zeros(n, dtype=float)
    if n > 1:
        changes[1:] = (labels_arr[1:] != labels_arr[:-1]).astype(float)

    churn = np.zeros(n, dtype=float)
    for i in range(n):
        window_start = max(0, i - churn_window + 1)
        churn[i] = float(np.mean(changes[window_start : i + 1]))
    return churn


def _build_label_map(means: np.ndarray) -> dict[int, str]:
    """Map integer HMM states to canonical regime text labels.

    Sorted deterministically by fitted emission mean[:, 0] (log-return dimension).
    Assignment by rank:

      K=2: order[0]->trending_down, order[1]->trending_up
      K=3: order[0]->trending_down, order[2]->trending_up, order[1]->ranging
      K=4: order[0]->trending_down, order[3]->trending_up,
           order[1]->ranging, order[2]->transition
      K=5: order[0]->trending_down, order[4]->trending_up,
           order[1]->transition_down, order[3]->transition_up, order[2]->ranging
      K>5: extremes get trending_down/up, next-inward get transition_down/up,
           all remaining middle states get ranging.

    This produces semantically stable labels regardless of which integer
    hmmlearn assigns to which state.

    Args:
        means: Shape (K, n_features) -- emission means from fitted HMM.
                Column 0 is the log-return dimension used for sorting.

    Returns:
        dict mapping integer state index -> canonical text label.
    """
    n_components = means.shape[0]
    means_ret = means[:, 0]  # log-return dimension
    order = np.argsort(means_ret)  # ascending: [most_neg, ..., most_pos]
    label_map: dict[int, str] = {}

    # Extremes are always trending_down / trending_up
    label_map[int(order[0])] = _LABEL_TRENDING_DOWN
    label_map[int(order[-1])] = _LABEL_TRENDING_UP

    if n_components >= 4:
        # Second from each extreme are transition states
        label_map[int(order[1])] = _LABEL_TRANSITION_DOWN
        label_map[int(order[-2])] = _LABEL_TRANSITION_UP

    # All remaining middle states are ranging
    for i in range(n_components):
        if i not in label_map:
            label_map[i] = _LABEL_RANGING

    return label_map


# ---------------------------------------------------------------------------
# Per-(symbol, tf) labeling
# ---------------------------------------------------------------------------


def _compute_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    n_components: int,
    vol_window: int,
    n_iter: int,
    hmm_random_state: int,
    momentum_window: int,
    vol_of_vol_window: int,
    covariance_type: str = "full",
    min_hold_bars: int = 3,
    heldout_fraction: float = 0.2,
    full_cov_min_obs: int = 500,
    min_state_occupation: float = 0.05,
    churn_window: int = 10,
) -> tuple[list[tuple], bool, float] | None:
    """Fit HMM for one (symbol, tf) cell. Returns (update_rows, converged, heldout_ll) or None.

    No DB writes — clears any open transaction before the server-side cursor, then runs pure
    HMM compute. Each tuple in update_rows matches the UPDATE SQL parameter order:
    (regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration, hmm_churn, symbol, tf, ts).

    Returns None if OHLCV is absent/insufficient (existing behavior) OR if the
    occupation gate (P2b) flags the fit as degenerate/non-converged/too-short —
    _check_occupation_gate's skip reasons all funnel into this same None marker
    so _run_symbol_worker/main() handle every skip path uniformly.
    """
    timestamps = []
    closes = []
    volumes = []
    # Server-side cursor requires no active transaction — commit any open transaction first.
    conn.commit()
    with conn.cursor("ohlcv_stream") as cur:
        cur.execute(
            "SELECT timestamp, close, volume "
            "FROM market_data_ohlcv "
            "WHERE symbol = %s AND timeframe = %s AND volume > 0 "
            "ORDER BY timestamp ASC",
            (symbol, tf),
        )
        while True:
            batch = cur.fetchmany(10000)
            if not batch:
                break
            for r in batch:
                timestamps.append(r[0])
                closes.append(float(r[1]))
                volumes.append(float(r[2]))

    if not timestamps:
        _logger.warning("regime_writer.no_ohlcv", symbol=symbol, tf=tf)
        return None

    obs_matrix, valid_ts = _build_obs_matrix(
        timestamps,
        closes,
        volumes,
        vol_window=vol_window,
        momentum_window=momentum_window,
        vol_of_vol_window=vol_of_vol_window,
    )

    min_rows = n_components * _MIN_OBS_FACTOR
    if len(valid_ts) < min_rows:
        _logger.warning(
            "regime_writer.insufficient_obs",
            symbol=symbol,
            tf=tf,
            n_obs=len(valid_ts),
            min_required=min_rows,
        )
        return None

    # Standardize per-series: fit on this series, transform in-place.
    # Both fit() and alpha-pass receive the scaled matrix so means/covars
    # are in scaled space — internally consistent.
    scaler = StandardScaler()
    obs_matrix = scaler.fit_transform(obs_matrix)

    # Fall back to diag if too few observations for full covariance to be reliable.
    eff_cov_type = covariance_type if len(obs_matrix) >= full_cov_min_obs else "diag"

    model = GaussianHMM(
        n_components=n_components,
        covariance_type=eff_cov_type,
        n_iter=n_iter,
        random_state=hmm_random_state,
    )
    model.fit(obs_matrix)

    # Convergence check — non-convergence means EM stopped early; labels are valid
    # but may be suboptimal. Retry once with doubled iterations before proceeding.
    converged = bool(model.monitor_.converged)
    if not converged:
        _logger.warning(
            "regime_writer.hmm_not_converged_retry",
            symbol=symbol,
            tf=tf,
            n_iter=n_iter,
        )
        retry_model = GaussianHMM(
            n_components=n_components,
            covariance_type=eff_cov_type,
            n_iter=n_iter * 2,
            random_state=hmm_random_state,
        )
        retry_model.fit(obs_matrix)
        if retry_model.monitor_.converged:
            model = retry_model
            converged = True
        else:
            _logger.warning(
                "regime_writer.hmm_not_converged_final",
                symbol=symbol,
                tf=tf,
                n_iter=n_iter * 2,
            )

    # Held-out log-likelihood: score last heldout_fraction of bars.
    # Model is fit on full series; this is diagnostic only — does not gate write.
    heldout_ll = float("nan")
    n_obs = len(obs_matrix)
    n_holdout = max(1, int(n_obs * heldout_fraction))
    if n_holdout >= n_components:
        try:
            heldout_ll = float(model.score(obs_matrix[-n_holdout:]) / n_holdout)
        except Exception:
            pass

    # Stationary prior — replaces uniform 1/K with long-run state probabilities.
    pi0 = _stationary_distribution(model.transmat_)

    # Precompute log emissions then run causal alpha-pass.
    if eff_cov_type == "full":
        log_emit = _log_emit_full(obs_matrix, model.means_, model.covars_)
    else:
        d = model.means_.shape[1]
        if model.covars_.ndim == 3:
            covars_diag = model.covars_[:, np.arange(d), np.arange(d)]
        else:
            covars_diag = model.covars_
        log_emit = _log_emit_diag(obs_matrix, model.means_, covars_diag)

    log_A = np.log(np.maximum(model.transmat_, 1e-300))
    raw_states, alpha_history = _alpha_pass_jit(log_emit, log_A, pi0)

    # Minimum holding-period smoothing — prevents single-bar flips when alpha is diffuse.
    smoothed_states = _smooth_states(raw_states, min_hold_bars)

    # P2b degenerate-model gate — must run BEFORE building update_rows so a
    # collapsed/non-converged fit never reaches feature_vectors. See
    # _check_occupation_gate for the empty/short/non-converged/degenerate cases
    # it guards against, all funneled into the same None skip marker used by the
    # pre-existing no_ohlcv/insufficient_obs early-returns above.
    is_degenerate, gate_info = _check_occupation_gate(
        smoothed_states, n_components, min_state_occupation, converged
    )
    if is_degenerate:
        _logger.warning(
            "regime_writer.degenerate_model_skipped",
            symbol=symbol,
            tf=tf,
            min_state_occupation=min_state_occupation,
            **gate_info,
        )
        return None

    label_map = _build_label_map(model.means_)
    # For K>=4, hmm_prob_trending_up/down aggregate all bullish/bearish probability mass.
    # bullish_states: all states labeled trending_up or transition_up
    # bearish_states: all states labeled trending_down or transition_down
    # ranging_states: all states labeled ranging (typically one middle state)
    bullish_states = [k for k, v in label_map.items() if v in _BULLISH_LABELS]
    bearish_states = [k for k, v in label_map.items() if v in _BEARISH_LABELS]
    ranging_states = [k for k, v in label_map.items() if v == _LABEL_RANGING]

    # P2c hmm_churn — rolling label-change rate over the prior churn_window bars.
    # Computed on the actual mapped labels (not raw state indices) so it stays
    # correct even when n_components > 5 lets two distinct states share a label.
    labels_seq = [label_map[int(s)] for s in smoothed_states]
    churn_values = _compute_hmm_churn(labels_seq, churn_window)

    # Explicit loop — required for index-based alpha_history access and stateful
    # duration counter simultaneously. Uses smoothed states for regime label and
    # duration; alpha_history reflects the raw forward-filter probability.
    update_rows: list[tuple] = []
    prev_state: int | None = None
    duration = 0
    for i, (ts, state_idx) in enumerate(zip(valid_ts, smoothed_states)):
        state_idx = int(state_idx)
        if state_idx == prev_state:
            duration += 1
        else:
            duration = 1
            prev_state = state_idx
        alpha = alpha_history[i]
        p_up = float(sum(alpha[s] for s in bullish_states))
        p_ranging = float(sum(alpha[s] for s in ranging_states))
        p_down = float(sum(alpha[s] for s in bearish_states))
        prob_val = float(np.max(alpha))
        entropy_val = float(-np.sum(alpha * np.log(np.maximum(alpha, 1e-300))))
        update_rows.append(
            (
                label_map[state_idx],
                p_up,
                p_ranging,
                p_down,
                prob_val,
                entropy_val,
                float(duration),
                float(churn_values[i]),
                symbol,
                tf,
                ts,
            )
        )

    return update_rows, converged, heldout_ll


def _write_regime_results(
    conn: Any,
    symbol: str,
    tf: str,
    update_rows: list[tuple],
    converged: bool,
    heldout_ll: float,
    tracer: Any,
) -> int:
    """Write HMM regime labels for one (symbol, tf) cell to feature_vectors.

    Runs in the main process — single serial write connection, no concurrency.
    Returns n_updated.
    """
    with tracer.start_as_current_span(
        "regime_writer.write_symbol_tf",
        attributes={"symbol": symbol, "tf": tf},
    ) as span:
        try:
            _bulk_update_by_key(
                conn,
                table="feature_vectors",
                temp_table="_regime_writer_staging",
                key_cols=["symbol", "tf", "bar_ts"],
                set_cols=[
                    "regime",
                    "hmm_prob_trending_up",
                    "hmm_prob_ranging",
                    "hmm_prob_trending_down",
                    "hmm_regime_prob",
                    "hmm_entropy",
                    "hmm_duration",
                    "hmm_churn",
                ],
                col_types={
                    "regime": "text",
                    "hmm_prob_trending_up": "double precision",
                    "hmm_prob_ranging": "double precision",
                    "hmm_prob_trending_down": "double precision",
                    "hmm_regime_prob": "double precision",
                    "hmm_entropy": "double precision",
                    "hmm_duration": "double precision",
                    "hmm_churn": "double precision",
                    "symbol": "text",
                    "tf": "text",
                    "bar_ts": "timestamptz",
                },
                rows=update_rows,
            )
            conn.commit()
            # Single query returns both counts in one round trip.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT "
                    "  count(*) FILTER (WHERE regime IS NOT NULL), "
                    "  count(*) FILTER (WHERE regime IS NULL) "
                    "FROM feature_vectors WHERE symbol = %s AND tf = %s",
                    (symbol, tf),
                )
                n_updated, remaining = cur.fetchone()
                n_updated = int(n_updated)
                remaining = int(remaining)

            REGIME_WRITER_NULL_REGIME_REMAINING.set(remaining, {"symbol": symbol, "tf": tf})
            span.set_attribute("n_updated", n_updated)
            span.set_attribute("null_remaining", remaining)
            _logger.info(
                "regime_writer.symbol_tf_done",
                symbol=symbol,
                tf=tf,
                n_updated=n_updated,
                null_remaining=remaining,
                converged=converged,
                heldout_ll_per_obs=round(heldout_ll, 4) if math.isfinite(heldout_ll) else None,
            )
            return n_updated

        except Exception as error:
            from opentelemetry.trace import StatusCode

            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise


# ---------------------------------------------------------------------------
# Symbol discovery
# ---------------------------------------------------------------------------


def _discover_symbols(conn: Any) -> list[str]:
    """Return symbols that have at least one un-labeled row in feature_vectors.

    Skips symbols where every row already has a regime, so restarts are safe.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM feature_vectors" " WHERE regime IS NULL ORDER BY symbol"
        )
        return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Subprocess worker for ProcessPoolExecutor
# ---------------------------------------------------------------------------


def _run_symbol_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg2 connection for OHLCV reads only. Runs HMM compute
    and returns update_rows to the main process; never writes to the DB.

    Args:
        args: (symbol, tfs, dsn, n_components, vol_window, momentum_window,
               vol_of_vol_window, n_iter, hmm_random_state, covariance_type,
               min_hold_bars, heldout_fraction, full_cov_min_obs,
               min_state_occupation, churn_window)

    Returns:
        dict with keys:
          symbol: str
          results: list of {tf, update_rows, converged, heldout_ll} or {tf, error}
          error: str | None  (set if connection itself failed)
    """
    (
        symbol,
        tfs,
        dsn,
        n_components,
        vol_window,
        momentum_window,
        vol_of_vol_window,
        n_iter,
        hmm_random_state,
        covariance_type,
        min_hold_bars,
        heldout_fraction,
        full_cov_min_obs,
        min_state_occupation,
        churn_window,
    ) = args

    setup_service_logging("logs/regime_writer.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg2.connect(dsn, options="-c idle_in_transaction_session_timeout=0")

        for tf in tfs:
            try:
                result = _compute_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    n_components=n_components,
                    vol_window=vol_window,
                    momentum_window=momentum_window,
                    vol_of_vol_window=vol_of_vol_window,
                    n_iter=n_iter,
                    hmm_random_state=hmm_random_state,
                    covariance_type=covariance_type,
                    min_hold_bars=min_hold_bars,
                    heldout_fraction=heldout_fraction,
                    full_cov_min_obs=full_cov_min_obs,
                    min_state_occupation=min_state_occupation,
                    churn_window=churn_window,
                )
                if result is None:
                    results.append(
                        {
                            "tf": tf,
                            "update_rows": None,
                            "converged": False,
                            "heldout_ll": float("nan"),
                        }
                    )
                else:
                    update_rows, converged, heldout_ll = result
                    results.append(
                        {
                            "tf": tf,
                            "update_rows": update_rows,
                            "converged": converged,
                            "heldout_ll": heldout_ll,
                        }
                    )
            except Exception as error:
                worker_log.error(
                    "regime_writer.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
                results.append({"tf": tf, "update_rows": None, "error": str(error)})
                try:
                    conn.rollback()
                except Exception:
                    # Connection is dead; remaining TFs for this symbol would also fail.
                    break

    except Exception as error:
        error_msg = str(error)
        worker_log.error("regime_writer.worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {"symbol": symbol, "results": results, "error": error_msg}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run regime labeler across all (symbol, tf) cells."""
    parser = argparse.ArgumentParser(description="Populate feature_vectors.regime via causal HMM")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Symbols to label (default: all distinct symbols in feature_vectors)",
    )
    parser.add_argument(
        "--tf",
        nargs="*",
        default=_DEFAULT_TFS,
        help=f"Timeframes to label (default: {_DEFAULT_TFS})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: APR infra.regime_writer.workers, fallback 1)",
    )
    parser.add_argument(
        "--refit",
        action="store_true",
        default=False,
        help=(
            "Force regime re-labeling only (feature_vectors compute already done). "
            "Semantic documentation flag — regime_writer always fits GaussianHMM from scratch; "
            "--refit signals intent to callers that this run re-labels an existing corpus."
        ),
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # OTel init (graceful — metrics are hard failure, traces optional)
    # ------------------------------------------------------------------
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning(
            "regime_writer.otel_init_failed",
            error=str(error),
            note="Continuing without OTel — metrics will not reach collector",
        )

    if args.refit:
        _logger.info(
            "regime_writer.refit_mode",
            note="Running in refit mode: re-labeling regimes only, feature_vectors compute already complete.",
        )

    tracer = trace.get_tracer("indicagent")
    t0 = time.monotonic()
    status = "success"

    try:
        settings = Settings()
        dsn = settings.database_url

        with tracer.start_as_current_span("regime_writer.run") as run_span:
            # Open a short-lived connection for APR load + symbol discovery, then close it.
            # Workers open their own connections — nothing is shared across processes.
            _conn = psycopg2.connect(
                dsn,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                cfg = _load_config_service_shared(_conn)
                n_components = int(cfg.get_sync("feature.hmm.n_components", 3))
                vol_window = int(cfg.get_sync("feature.hmm.vol_window", 20))
                n_iter = int(cfg.get_sync("feature.hmm.n_iter", 200))
                hmm_random_state = int(cfg.get_sync("alpha.hmm.random_state", 42))
                momentum_window = int(cfg.get_sync("feature.hmm.obs_momentum_window", 20))
                vol_of_vol_window = int(cfg.get_sync("feature.hmm.obs_vol_of_vol_window", 20))
                covariance_type = cfg.get_sync("feature.hmm.covariance_type", "full")
                min_hold_bars = int(cfg.get_sync("feature.hmm.min_hold_bars", 3))
                heldout_fraction = float(cfg.get_sync("feature.hmm.heldout_fraction", 0.2))
                full_cov_min_obs = int(cfg.get_sync("feature.hmm.full_cov_min_obs", 500))
                min_state_occupation = float(cfg.get_sync("feature.hmm.min_state_occupation", 0.05))
                churn_window = int(cfg.get_sync("feature.hmm.churn_window", 10))

                symbols = args.symbols if args.symbols else _discover_symbols(_conn)
                tfs: list[str] = args.tf

                n_workers = args.workers
                if n_workers is None:
                    n_workers = int(cfg.get_sync("infra.regime_writer.workers", 1))
            finally:
                _conn.close()
            # dsn is passed to workers; no connection is held in main beyond this point.

            _logger.info(
                "regime_writer.starting",
                symbols_count=len(symbols),
                tfs=tfs,
                n_components=n_components,
                vol_window=vol_window,
                momentum_window=momentum_window,
                vol_of_vol_window=vol_of_vol_window,
                n_iter=n_iter,
                n_workers=n_workers,
                covariance_type=covariance_type,
                min_hold_bars=min_hold_bars,
                heldout_fraction=heldout_fraction,
                min_state_occupation=min_state_occupation,
                churn_window=churn_window,
            )

            worker_args = [
                (
                    symbol,
                    tfs,
                    dsn,
                    n_components,
                    vol_window,
                    momentum_window,
                    vol_of_vol_window,
                    n_iter,
                    hmm_random_state,
                    covariance_type,
                    min_hold_bars,
                    heldout_fraction,
                    full_cov_min_obs,
                    min_state_occupation,
                    churn_window,
                )
                for symbol in symbols
            ]

            # Pre-compile the JIT in the main process before spawning workers.
            # With cache=True the compile writes __pycache__ once; workers then load
            # the artifact read-only — no concurrent compile, no file-lock race.
            # No initializer= argument needed; start-method agnostic (fork and spawn).
            _jit_emit = np.zeros((10, n_components), dtype=np.float64)
            _jit_log_A = np.log(np.full((n_components, n_components), 1.0 / n_components))
            _jit_pi0 = np.full(n_components, 1.0 / n_components)
            _alpha_pass_jit(_jit_emit, _jit_log_A, _jit_pi0)
            _logger.info("regime_writer.jit_ready", n_components=n_components)

            total_updated = 0
            failures: list[str] = []

            write_conn = psycopg2.connect(
                dsn,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                with ProcessPoolExecutor(max_workers=n_workers) as pool:
                    for result in pool.map(_run_symbol_worker, worker_args, chunksize=1):
                        symbol = result["symbol"]
                        if result["error"]:
                            failures.append(symbol)
                            _logger.error(
                                "regime_writer.symbol_failed",
                                symbol=symbol,
                                error=result["error"],
                            )
                        for cell in result["results"]:
                            tf = cell["tf"]
                            if "error" in cell:
                                failures.append(f"{symbol}/{tf}")
                                continue
                            if cell["update_rows"] is None:
                                continue
                            try:
                                n = _write_regime_results(
                                    conn=write_conn,
                                    symbol=symbol,
                                    tf=tf,
                                    update_rows=cell["update_rows"],
                                    converged=cell.get("converged", False),
                                    heldout_ll=cell.get("heldout_ll", float("nan")),
                                    tracer=tracer,
                                )
                                total_updated += n
                                REGIME_WRITER_ROWS_UPDATED_TOTAL.add(
                                    n, {"symbol": symbol, "tf": tf}
                                )
                            except Exception as error:
                                _logger.error(
                                    "regime_writer.write_failed",
                                    symbol=symbol,
                                    tf=tf,
                                    error=str(error),
                                )
                                failures.append(f"{symbol}/{tf}")
                                try:
                                    write_conn.rollback()
                                except Exception:
                                    pass
            finally:
                write_conn.close()

            elapsed_s = time.monotonic() - t0
            REGIME_WRITER_RUN_LATENCY_SECONDS.record(elapsed_s)

            run_span.set_attribute("total_updated", total_updated)
            run_span.set_attribute("failed_cells", len(failures))

            _logger.info(
                "regime_writer.run_complete",
                total_updated=total_updated,
                failed_cells=failures,
                elapsed_s=round(elapsed_s, 2),
            )

            if failures:
                _logger.warning(
                    "regime_writer.partial_failure",
                    failed_cells=failures,
                    note="Some cells failed; overall run still marked success if >0 cells completed",
                )

    except Exception as error:
        status = "failure"
        _logger.error("regime_writer.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
        if status == "failure":
            sys.exit(1)


if __name__ == "__main__":
    main()
