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

KNOWN, REASONED EXCLUSIONS (todo 168, investigated 2026-07-24 — do not re-investigate
from scratch, read this first): the following (symbol, tf) cells reliably fail
_check_occupation_gate (degenerate_occupation) and are NOT a bug:
  - LQD, PFF, USMV: degenerate/near-miss at EVERY tf (1d included)
  - EFA, FXI: 1h only
  - FXY: 15m, 1h (15m is a severe collapse, min_fraction ~0.00008)
  - RSP: 15m, 1h, 5m
  - UUP: 15m, 5m (5m is a true collapse, two of five states never occur)
  - VWO, XRT: 5m only
Ruled out as causes (don't re-test these): the min_state_occupation=0.05 floor itself
(corpus-wide distribution check across 198 already-successful (symbol,tf) cells shows
the worst successful fit is 0.0502 — right at the floor, not evidence of miscalibration)
and min_hold_bars smoothing (tested directly at 1/2/3/5 against 3 of the worst cases,
zero effect). Pattern: near-universal success at 1d, failures concentrated at intraday
tf, for lower-beta/mean-reverting instrument types (bonds, preferred shares, low-vol
factor, currency ETFs) — reads as a genuine limit of a uniform K=5 trend-state HMM at
high frequency for these instruments, not a defect. Do not force these onto K=5 by
construction; a per-symbol K override was considered and rejected as unwarranted
complexity for a bounded, already-identified set of cells.

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
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import structlog
from hmmlearn.hmm import GaussianHMM
from opentelemetry import trace
from sklearn.preprocessing import StandardScaler

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import bulk_update_by_key as _bulk_update_by_key
from services._batch_utils import load_config_service_sync as _load_config_service_shared
from services._batch_utils import make_worker_pool as _make_worker_pool
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.features.feature_vector_persistence import (
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
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
# APR fallback default, live value read from feature.hmm.min_obs_factor (migration 275,
# todo 009 Part A).
_MIN_OBS_FACTOR_DEFAULT = 50

# todo 248 walk-forward HMM: (refit_every_bars, initial_warmup_bars) per tf, APR
# fallback defaults only (live values read per-tf from
# alpha.hmm.walk_forward.refit_every_bars.<tf> / .initial_warmup_bars.<tf>, migration
# TBD). 1h is the pilot's directly-measured value; 15m is the broadened pilot's own
# independently-confirmed value (same schedule, 4x bar density); 5m scales the same
# schedule by its own 12x density ratio (not independently piloted); 1d is a fresh,
# unpiloted ~1yr-refit/~2yr-warmup estimate at daily bar density. See
# docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md for the full derivation and
# per-tf certainty caveats.
_WALK_FORWARD_DEFAULT_PARAMS: dict[str, tuple[int, int]] = {
    "5m": (19800, 39600),
    "15m": (6600, 13200),
    "1h": (1650, 3300),
    "1d": (252, 504),
}

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


def _compute_log_emit(
    obs: np.ndarray, means: np.ndarray, covars: np.ndarray, cov_type: str
) -> np.ndarray:
    """Dispatch to _log_emit_full/_log_emit_diag based on a fitted model's own
    covariance_type, handling the diag-covars-from-a-full-shaped-array extraction
    (hmmlearn stores diag covars as (K, d, d) with off-diagonals zeroed OR as (K, d)
    depending on version/path -- both are handled here).

    Shared by every caller that needs log emissions from an already-fitted
    GaussianHMM (`_walk_forward_hmm_labels`, `_hmm_seed_stability_check`,
    `_compute_symbol_tf`, `_walk_forward_hmm_full`) -- this exact ~10-line dispatch
    was independently copy-pasted at all 4 call sites before being extracted here;
    factoring it out means a future fix (e.g. to the ndim==3 guard) lands once.
    """
    if cov_type == "full":
        return _log_emit_full(obs, means, covars)
    d = means.shape[1]
    covars_diag = covars[:, np.arange(d), np.arange(d)] if covars.ndim == 3 else covars
    return _log_emit_diag(obs, means, covars_diag)


def _state_groups(label_map: dict[int, str]) -> tuple[list[int], list[int], list[int]]:
    """This model's bullish/ranging/bearish STATE-INDEX sets, derived from its own
    label_map. Meaningful only relative to THIS specific fit -- state 2 in one
    independently-fit model has no relationship to state 2 in another (raw indices
    are not comparable across fits; see `_seed_prior_from_label`'s docstring).

    Returns (bullish_states, ranging_states, bearish_states).
    """
    bullish_states = [k for k, v in label_map.items() if v in _BULLISH_LABELS]
    ranging_states = [k for k, v in label_map.items() if v == _LABEL_RANGING]
    bearish_states = [k for k, v in label_map.items() if v in _BEARISH_LABELS]
    return bullish_states, ranging_states, bearish_states


def _alpha_history_to_regime_probs(
    alpha_history: np.ndarray,
    bullish_states: list[int],
    ranging_states: list[int],
    bearish_states: list[int],
) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """Vectorized per-bar (p_up, p_ranging, p_down, prob_val, entropy_val) from a
    segment's alpha vectors -- shared by `_compute_symbol_tf` and
    `_walk_forward_hmm_full`, both of which previously computed this identically
    via a per-bar Python loop (`sum(alpha[s] for s in states)` + per-bar np.max/
    np.sum/np.log calls). Operating on the whole (n, K) array at once instead of
    row-by-row is both less code and meaningfully cheaper at corpus scale (tens of
    thousands of bars per segment).

    alpha_history: shape (n, K), one row per bar.
    Returns 5 lists, each length n, index-aligned to alpha_history's rows.
    """
    p_up = (
        alpha_history[:, bullish_states].sum(axis=1)
        if bullish_states
        else np.zeros(len(alpha_history))
    )
    p_ranging = (
        alpha_history[:, ranging_states].sum(axis=1)
        if ranging_states
        else np.zeros(len(alpha_history))
    )
    p_down = (
        alpha_history[:, bearish_states].sum(axis=1)
        if bearish_states
        else np.zeros(len(alpha_history))
    )
    prob_val = alpha_history.max(axis=1)
    entropy_val = -np.sum(alpha_history * np.log(np.maximum(alpha_history, 1e-300)), axis=1)
    return (
        p_up.tolist(),
        p_ranging.tolist(),
        p_down.tolist(),
        prob_val.tolist(),
        entropy_val.tolist(),
    )


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


def _seed_prior_from_label(
    label_map: dict[int, str],
    label: str,
    n_components: int,
    fallback_prior: np.ndarray,
) -> np.ndarray:
    """One-hot prior over label_map's states, concentrated on whichever state THIS model's
    own label_map maps to `label`. Used to carry belief continuity across a walk-forward HMM
    refit boundary (`_walk_forward_hmm_labels`) -- raw state indices are not comparable
    across independently-fit models (state 0 can mean a different regime in each fit), but
    semantic labels are, since `_build_label_map` normalizes every fit's clusters onto the
    same fixed vocabulary. Falls back to `fallback_prior` if `label` isn't present in this
    model's map -- unreachable at K=5 (every label maps to exactly one state) but a real
    possibility at K>5 (todo 207's `_build_label_map` docstring), so fail safe rather than
    divide by zero."""
    pi0 = np.zeros(n_components, dtype=float)
    for state_idx, state_label in label_map.items():
        if state_label == label:
            pi0[state_idx] = 1.0
    if pi0.sum() == 0.0:
        return fallback_prior
    return pi0 / pi0.sum()


def _walk_forward_hmm_labels(
    obs_matrix: np.ndarray,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    hmm_random_state: int,
    refit_every_bars: int,
    initial_warmup_bars: int,
    min_hold_bars: int,
    full_cov_min_obs: int,
) -> tuple[list[str], list[tuple[int, int, int]]]:
    """Walk-forward alternative to `_compute_symbol_tf`'s single full-series HMM fit
    (todo 026/248, P4a): refits the model periodically using only the training-slice prefix
    up to each refit boundary, then causally decodes the next segment forward with that
    period's model before refitting again. At any bar t, the model that labeled it was fit
    using only data through the most recent refit boundary <= t -- eliminates the
    parameter-level lookahead channel `_compute_symbol_tf` has (decode is already causal;
    the model's own parameters previously were not, confirmed empirically:
    `docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md`).

    Each new segment's model is seeded with an initial belief (`pi0`) derived from the label
    the PREVIOUS segment ended on (`_seed_prior_from_label`), not a fresh stationary
    distribution -- a stationary prior throws away real information about which regime the
    series was just in. The first segment (no predecessor) uses its own stationary
    distribution, same as `_compute_symbol_tf`.

    `StandardScaler` is refit per segment (transform-only on the segment being decoded, fit
    only on that segment's own training prefix) -- a globally-fit scaler is the same class of
    leak in miniature.

    Returns:
        labels: semantic regime label per bar, aligned 1:1 with
            `obs_matrix[initial_warmup_bars:]` (bars before that have no walk-forward label --
            insufficient history for even the first fit).
        segments: list of (train_end, seg_start, seg_end) per refit -- train_end is the fit
            boundary actually used (obs_matrix[:train_end] was the only data the segment's
            model ever saw), seg_start/seg_end is the bar-index range it labeled. Exposed for
            causality verification, not needed by ordinary callers.
    """
    n = len(obs_matrix)
    if n < initial_warmup_bars + n_components:
        raise ValueError(
            f"Insufficient history for walk-forward HMM: {n} obs, "
            f"need >= {initial_warmup_bars + n_components}"
        )

    labels: list[str] = []
    segments: list[tuple[int, int, int]] = []
    boundary = initial_warmup_bars
    prior_label: str | None = None

    while boundary < n:
        train_slice = obs_matrix[:boundary]
        scaler = StandardScaler()
        train_scaled = scaler.fit_transform(train_slice)

        eff_cov_type = covariance_type if len(train_scaled) >= full_cov_min_obs else "diag"
        model = GaussianHMM(
            n_components=n_components,
            covariance_type=eff_cov_type,
            n_iter=n_iter,
            random_state=hmm_random_state,
        )
        model.fit(train_scaled)
        label_map = _build_label_map(model.means_)

        stationary_prior = _stationary_distribution(model.transmat_)
        if prior_label is None:
            pi0 = stationary_prior
        else:
            pi0 = _seed_prior_from_label(label_map, prior_label, n_components, stationary_prior)

        seg_end = min(boundary + refit_every_bars, n)
        seg_scaled = scaler.transform(obs_matrix[boundary:seg_end])
        log_emit = _compute_log_emit(seg_scaled, model.means_, model.covars_, eff_cov_type)
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
        raw_states, _ = _alpha_pass_jit(log_emit, log_A, pi0)
        smoothed = _smooth_states(raw_states, min_hold_bars)
        seg_labels = [label_map[int(s)] for s in smoothed]

        labels.extend(seg_labels)
        segments.append((boundary, boundary, seg_end))
        prior_label = seg_labels[-1]
        boundary = seg_end

    return labels, segments


def _walk_forward_hmm_full(
    obs_matrix: np.ndarray,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    hmm_random_state: int,
    refit_every_bars: int,
    initial_warmup_bars: int,
    min_hold_bars: int,
    full_cov_min_obs: int,
    min_state_occupation: float,
) -> list[dict[str, Any]]:
    """Production-parity walk-forward decode (todo 248): per-segment version of
    `_walk_forward_hmm_labels` that additionally returns the per-bar alpha vectors,
    each segment's own convergence status, and each segment's own degenerate-occupation
    gate result -- everything `_compute_symbol_tf_walk_forward` needs to assemble
    `feature_vectors`' full column set (p_up/p_ranging/p_down/prob/entropy/duration),
    not just the bare regime label `_walk_forward_hmm_labels` returns.

    Kept as a separate function rather than extending `_walk_forward_hmm_labels` in
    place: that function's existing (labels, segments) contract is exercised by the
    Gate 4 pilot scripts and their own tests (docs/analysis/hmm-parameter-lookahead-pilot-*.md);
    changing its return shape would silently break those without touching their code.
    The per-segment refit/decode logic itself is intentionally duplicated (not
    delegated to the other function) because the alpha vectors this function needs
    are exactly the array `_walk_forward_hmm_labels` computes and then discards
    (`raw_states, _ = _alpha_pass_jit(...)`) -- delegating would mean re-running the
    HMM fit and decode a second time per segment, doubling the walk-forward path's
    compute cost for no reason.

    Each segment gets the SAME non-convergence retry `_compute_symbol_tf` gives its
    single full-series fit (doubled n_iter, one retry) -- omitting it here would make
    every genuinely-recoverable segment more likely to trip the degenerate gate below
    purely from under-iterating, not from an actual bad fit.

    Returns one dict per refit segment (NOT one dict per bar), each:
        {
            "seg_start": int, "seg_end": int,  # half-open [seg_start, seg_end) bar-index
                range into obs_matrix / valid_ts (both 1:1 index-aligned by construction)
            "labels": list[str],        # len == seg_end - seg_start
            "p_up": list[float], "p_ranging": list[float], "p_down": list[float],
            "prob_val": list[float], "entropy_val": list[float],  # same length, one
                per bar -- computed here (not by the caller) because bullish/ranging/
                bearish STATE-INDEX membership is only meaningful relative to THIS
                segment's own `label_map` (state 2 in one segment's independently-fit
                model has no relationship to state 2 in the next segment's model);
                exposing raw alpha + a bare label_map to the caller would just move
                this same per-segment index resolution into the caller for no benefit.
            "converged": bool,
            "is_degenerate": bool,     # _check_occupation_gate's verdict for this segment
            "gate_info": dict,         # _check_occupation_gate's diagnostics for this segment
        }
    Degenerate/non-converged segments ARE included (not silently dropped) -- this
    function is a pure reporter of what each segment's fit produced; the caller
    (`_compute_symbol_tf_walk_forward`) decides whether to write a segment's bars,
    mirroring the existing separation between `_check_occupation_gate` (decides) and
    `_compute_symbol_tf` (acts on the decision) in the single-fit path.
    """
    n = len(obs_matrix)
    if n < initial_warmup_bars + n_components:
        raise ValueError(
            f"Insufficient history for walk-forward HMM: {n} obs, "
            f"need >= {initial_warmup_bars + n_components}"
        )

    segment_results: list[dict[str, Any]] = []
    boundary = initial_warmup_bars
    prior_label: str | None = None

    while boundary < n:
        train_slice = obs_matrix[:boundary]
        scaler = StandardScaler()
        train_scaled = scaler.fit_transform(train_slice)

        eff_cov_type = covariance_type if len(train_scaled) >= full_cov_min_obs else "diag"
        model = GaussianHMM(
            n_components=n_components,
            covariance_type=eff_cov_type,
            n_iter=n_iter,
            random_state=hmm_random_state,
        )
        model.fit(train_scaled)
        converged = bool(model.monitor_.converged)
        if not converged:
            retry_model = GaussianHMM(
                n_components=n_components,
                covariance_type=eff_cov_type,
                n_iter=n_iter * 2,
                random_state=hmm_random_state,
            )
            retry_model.fit(train_scaled)
            if retry_model.monitor_.converged:
                model = retry_model
                converged = True

        label_map = _build_label_map(model.means_)

        stationary_prior = _stationary_distribution(model.transmat_)
        if prior_label is None:
            pi0 = stationary_prior
        else:
            pi0 = _seed_prior_from_label(label_map, prior_label, n_components, stationary_prior)

        seg_end = min(boundary + refit_every_bars, n)
        seg_scaled = scaler.transform(obs_matrix[boundary:seg_end])
        log_emit = _compute_log_emit(seg_scaled, model.means_, model.covars_, eff_cov_type)
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
        raw_states, alpha_history = _alpha_pass_jit(log_emit, log_A, pi0)
        smoothed = _smooth_states(raw_states, min_hold_bars)
        seg_labels = [label_map[int(s)] for s in smoothed]

        is_degenerate, gate_info = _check_occupation_gate(
            smoothed, n_components, min_state_occupation, converged
        )

        # This segment's own state groups, derived from its own label_map -- see
        # _state_groups' docstring for why raw state indices aren't comparable
        # across independently-fit segments.
        bullish_states, ranging_states, bearish_states = _state_groups(label_map)
        p_up_list, p_ranging_list, p_down_list, prob_val_list, entropy_val_list = (
            _alpha_history_to_regime_probs(
                alpha_history, bullish_states, ranging_states, bearish_states
            )
        )

        segment_results.append(
            {
                "seg_start": boundary,
                "seg_end": seg_end,
                "labels": seg_labels,
                "p_up": p_up_list,
                "p_ranging": p_ranging_list,
                "p_down": p_down_list,
                "prob_val": prob_val_list,
                "entropy_val": entropy_val_list,
                "converged": converged,
                "is_degenerate": is_degenerate,
                "gate_info": gate_info,
            }
        )
        prior_label = seg_labels[-1]
        boundary = seg_end

    return segment_results


def _compute_symbol_tf_walk_forward(
    conn: Any,
    symbol: str,
    tf: str,
    n_components: int,
    vol_window: int,
    n_iter: int,
    hmm_random_state: int,
    momentum_window: int,
    vol_of_vol_window: int,
    refit_every_bars: int,
    initial_warmup_bars: int,
    covariance_type: str = "full",
    min_hold_bars: int = 3,
    full_cov_min_obs: int = 500,
    min_state_occupation: float = 0.05,
    churn_window: int = 10,
    min_obs_factor: int = _MIN_OBS_FACTOR_DEFAULT,
) -> tuple[list[tuple], bool, float] | None:
    """Walk-forward alternative to `_compute_symbol_tf` (todo 248) -- same
    (update_rows, converged, heldout_ll) | None contract, so `_run_symbol_worker`'s
    caller only needs to branch on which function to call, not how to use the result.

    Bars before `initial_warmup_bars` (insufficient history for even the first
    refit) are simply ABSENT from `update_rows` -- never written, which for a
    freshly-recomputed `feature_vectors` row (regime IS NULL) leaves them
    correctly NULL rather than fabricating a value. `feature_vectors.regime`'s
    existing NULL is already a tracked, monitored state
    (`REGIME_WRITER_NULL_REGIME_REMAINING`), not an error condition -- this reuses
    that existing convention rather than inventing new NULL-writing logic.
    Precondition (not enforced by this function, must hold at the caller/deployment
    level): this must only run against rows that do not already carry a DIFFERENT
    method's regime value for the same (symbol, tf) -- e.g. right after a fresh
    `backfill_feature_factory.py --recompute` pass, which leaves `regime` NULL for
    every row. Running walk-forward as a partial re-run over a corpus already
    populated by the single-fit path would silently blend two different
    computation methods under one column for the warm-up-prefix bars (whatever
    they last held) versus the rest (freshly walk-forward-computed) -- see todo
    248's SUMMARY/deployment notes.

    Bars belonging to a degenerate or non-converged segment (`_walk_forward_hmm_full`'s
    per-segment gate) are also absent from `update_rows` -- skipped at SEGMENT
    granularity, not cell granularity: a bad fit in one multi-year window does not
    discard decades of otherwise-good segments the way `_compute_symbol_tf`'s single
    global gate would. `duration` (bars in the current regime) resets to a fresh
    count at the first bar following any skipped segment, since bar-to-bar
    continuity through an un-written gap cannot be verified.

    `converged` in the return tuple is True iff every segment that actually
    contributed rows to `update_rows` converged (skipped segments don't count
    against it, having contributed nothing). `heldout_ll` is always NaN: unlike
    the single-fit path's one held-out tail of one unified model, walk-forward has
    no single model whose held-out score is well-defined across segment
    boundaries -- honest NaN rather than inventing an ad hoc definition, consistent
    with this field's existing "diagnostic only, does not gate write" contract.
    """
    fetched = _fetch_obs_matrix(
        conn,
        symbol,
        tf,
        n_components,
        vol_window,
        momentum_window,
        vol_of_vol_window,
        min_obs_factor,
    )
    if fetched is None:
        return None
    obs_matrix, valid_ts = fetched

    try:
        segment_results = _walk_forward_hmm_full(
            obs_matrix,
            n_components,
            covariance_type,
            n_iter,
            hmm_random_state,
            refit_every_bars,
            initial_warmup_bars,
            min_hold_bars,
            full_cov_min_obs,
            min_state_occupation,
        )
    except ValueError:
        # Same "insufficient history" condition _walk_forward_hmm_full raises for
        # -- min_obs_factor's gate above already ensures n_components * min_obs_factor
        # rows exist, but initial_warmup_bars (tf-calibrated, can be large -- e.g.
        # 5m's ~39,600-bar warmup) is a stricter, independent floor. Same skip
        # marker as every other "not enough data" case in this file.
        _logger.warning(
            "regime_writer.walk_forward_insufficient_warmup",
            symbol=symbol,
            tf=tf,
            n_obs=len(valid_ts),
            initial_warmup_bars=initial_warmup_bars,
        )
        return None

    # Churn is a property of the LABEL SEQUENCE, not the fitting mechanism, so it is
    # computed once on the concatenation of every WRITTEN (non-degenerate) segment's
    # labels, in bar order -- same _compute_hmm_churn helper the single-fit path
    # uses, just fed a sequence that may have gaps at skipped-segment boundaries.
    # Those gaps are exactly where duration/prev_label also reset below, so churn's
    # own "first bar after a gap has no real predecessor" edge case lines up with
    # the same discontinuity duration already treats specially.
    all_written_labels: list[str] = []
    for seg in segment_results:
        if not seg["is_degenerate"]:
            all_written_labels.extend(seg["labels"])
    churn_values = _compute_hmm_churn(all_written_labels, churn_window)

    update_rows: list[tuple] = []
    any_written = False
    all_written_converged = True
    duration = 0
    prev_label: str | None = None
    churn_cursor = 0
    for seg in segment_results:
        if seg["is_degenerate"]:
            _logger.warning(
                "regime_writer.walk_forward_segment_skipped",
                symbol=symbol,
                tf=tf,
                seg_start=seg["seg_start"],
                seg_end=seg["seg_end"],
                **seg["gate_info"],
            )
            # Duration continuity cannot be trusted across a skipped gap.
            duration = 0
            prev_label = None
            continue

        any_written = True
        all_written_converged = all_written_converged and seg["converged"]
        seg_ts = valid_ts[seg["seg_start"] : seg["seg_end"]]

        for i, label in enumerate(seg["labels"]):
            if label == prev_label:
                duration += 1
            else:
                duration = 1
                prev_label = label
            update_rows.append(
                (
                    label,
                    seg["p_up"][i],
                    seg["p_ranging"][i],
                    seg["p_down"][i],
                    seg["prob_val"][i],
                    seg["entropy_val"][i],
                    float(duration),
                    float(churn_values[churn_cursor]),
                    symbol,
                    tf,
                    seg_ts[i],
                )
            )
            churn_cursor += 1

    if not any_written:
        _logger.warning(
            "regime_writer.walk_forward_all_segments_degenerate",
            symbol=symbol,
            tf=tf,
            n_segments=len(segment_results),
        )
        return None

    return update_rows, all_written_converged, float("nan")


def _hmm_seed_stability_check(
    obs_matrix: np.ndarray,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    seeds: list[int],
    full_cov_min_obs: int,
) -> dict:
    """Todo 026's bundled ask: fit `n_components`-state GaussianHMM once per seed in `seeds`
    on the SAME obs_matrix, compare log-likelihood and semantic-label agreement across seeds.
    Each `_walk_forward_hmm_labels` segment refit is itself a fresh non-convex EM
    optimization, subject to the same local-optima risk todo 108's multi-seed restart already
    addresses for `_compute_symbol_tf`'s single full-history fit -- this is the equivalent
    diagnostic for the walk-forward path, run once per segment by a caller, not itself part
    of `_walk_forward_hmm_labels`'s hot loop.

    Labels (not raw state indices) are compared pairwise, since raw indices are not
    comparable across independently-fit models -- `_build_label_map` normalizes each seed's
    own fit onto the same fixed vocabulary first.

    Returns:
        {
            "log_likelihoods": {seed: float, ...},
            "ll_spread": float,  # max - min log-likelihood across seeds
            "pairwise_label_agreement": {(seed_a, seed_b): float, ...},  # one entry per
                unique seed pair (seed_a < seed_b), fraction of bars where both seeds'
                semantic labels agree
            "min_pairwise_agreement": float,
        }
    """
    log_likelihoods: dict[int, float] = {}
    labels_by_seed: dict[int, list[str]] = {}

    for seed in seeds:
        eff_cov_type = covariance_type if len(obs_matrix) >= full_cov_min_obs else "diag"
        model = GaussianHMM(
            n_components=n_components,
            covariance_type=eff_cov_type,
            n_iter=n_iter,
            random_state=seed,
        )
        model.fit(obs_matrix)
        log_likelihoods[seed] = float(model.score(obs_matrix))

        label_map = _build_label_map(model.means_)
        pi0 = _stationary_distribution(model.transmat_)
        log_emit = _compute_log_emit(obs_matrix, model.means_, model.covars_, eff_cov_type)
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
        raw_states, _ = _alpha_pass_jit(log_emit, log_A, pi0)
        labels_by_seed[seed] = [label_map[int(s)] for s in raw_states]

    pairwise_label_agreement: dict[tuple[int, int], float] = {}
    for i, seed_a in enumerate(seeds):
        for seed_b in seeds[i + 1 :]:
            labels_a = labels_by_seed[seed_a]
            labels_b = labels_by_seed[seed_b]
            agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
            pairwise_label_agreement[(seed_a, seed_b)] = agree / len(labels_a)

    lls = list(log_likelihoods.values())
    return {
        "log_likelihoods": log_likelihoods,
        "ll_spread": max(lls) - min(lls),
        "pairwise_label_agreement": pairwise_label_agreement,
        "min_pairwise_agreement": min(pairwise_label_agreement.values()),
    }


# ---------------------------------------------------------------------------
# Per-(symbol, tf) labeling
# ---------------------------------------------------------------------------


def _fetch_obs_matrix(
    conn: Any,
    symbol: str,
    tf: str,
    n_components: int,
    vol_window: int,
    momentum_window: int,
    vol_of_vol_window: int,
    min_obs_factor: int,
) -> tuple[np.ndarray, list] | None:
    """Fetch OHLCV and build the raw (unscaled) HMM observation matrix for one
    (symbol, tf) cell. Shared prefix between `_compute_symbol_tf` (single full-series
    fit) and `_compute_symbol_tf_walk_forward` (todo 248) — both need the identical
    raw series; each then applies its OWN scaling policy (single-fit standardizes
    once globally, walk-forward standardizes per-segment on the training prefix
    only, per `_walk_forward_hmm_labels`'s docstring on why a globally-fit scaler
    is the same class of leak in miniature).

    Returns None if OHLCV is absent/insufficient — logs the same
    `regime_writer.no_ohlcv`/`regime_writer.insufficient_obs` events either caller
    previously logged inline, so behavior is unchanged by this extraction.
    """
    timestamps = []
    closes = []
    volumes = []
    # Server-side cursor requires no active transaction — commit any open transaction first.
    conn.commit()
    with conn.cursor("ohlcv_stream") as cur:
        cur.execute(
            "SELECT timestamp, close, volume "
            "FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s "
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

    min_rows = n_components * min_obs_factor
    if len(valid_ts) < min_rows:
        _logger.warning(
            "regime_writer.insufficient_obs",
            symbol=symbol,
            tf=tf,
            n_obs=len(valid_ts),
            min_required=min_rows,
        )
        return None

    return obs_matrix, valid_ts


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
    min_obs_factor: int = _MIN_OBS_FACTOR_DEFAULT,
    n_restarts: int = 1,
) -> tuple[list[tuple], bool, float] | None:
    """Fit HMM for one (symbol, tf) cell. Returns (update_rows, converged, heldout_ll) or None.

    No DB writes — clears any open transaction before the server-side cursor, then runs pure
    HMM compute. Each tuple in update_rows matches the UPDATE SQL parameter order:
    (regime, p_up, p_ranging, p_down, prob_val, entropy_val, duration, hmm_churn, symbol, tf, ts).

    n_restarts (APR: alpha.hmm.n_restarts, default 1) fits n_restarts seeds derived
    deterministically as hmm_random_state + i and keeps whichever converged model has
    the highest log-likelihood (todo 108). At the default of 1, only hmm_random_state
    itself is tried — same-seed convergence retry included — reproducing the prior
    single-seed behavior exactly.

    Returns None if OHLCV is absent/insufficient (existing behavior) OR if the
    occupation gate (P2b) flags the fit as degenerate/non-converged/too-short —
    _check_occupation_gate's skip reasons all funnel into this same None marker
    so _run_symbol_worker/main() handle every skip path uniformly.
    """
    fetched = _fetch_obs_matrix(
        conn,
        symbol,
        tf,
        n_components,
        vol_window,
        momentum_window,
        vol_of_vol_window,
        min_obs_factor,
    )
    if fetched is None:
        return None
    obs_matrix, valid_ts = fetched

    # Standardize per-series: fit on this series, transform in-place.
    # Both fit() and alpha-pass receive the scaled matrix so means/covars
    # are in scaled space — internally consistent.
    scaler = StandardScaler()
    obs_matrix = scaler.fit_transform(obs_matrix)

    # Fall back to diag if too few observations for full covariance to be reliable.
    eff_cov_type = covariance_type if len(obs_matrix) >= full_cov_min_obs else "diag"

    # Multi-seed restart (todo 108): fit n_restarts seeds derived deterministically as
    # hmm_random_state + i, keep whichever converged model has the highest log-likelihood.
    # GaussianHMM's EM objective is non-convex, so a single seed can land in a worse local
    # optimum than a different seed would find. Each seed still gets the original
    # same-seed convergence retry (doubled n_iter) before being scored, so this loop is a
    # strict superset of the old single-seed behavior: convergence always wins over
    # non-convergence, log-likelihood is the tiebreaker within the same convergence status.
    # At n_restarts=1 (APR default) exactly one seed (hmm_random_state itself) is tried,
    # so this reduces byte-for-byte to the historical single-seed-fit-plus-retry code path.
    model = None
    converged = False
    best_ll = float("-inf")
    for i in range(n_restarts):
        seed = hmm_random_state + i
        candidate = GaussianHMM(
            n_components=n_components,
            covariance_type=eff_cov_type,
            n_iter=n_iter,
            random_state=seed,
        )
        candidate.fit(obs_matrix)

        # Convergence check — non-convergence means EM stopped early; labels are valid
        # but may be suboptimal. Retry once with doubled iterations before proceeding.
        candidate_converged = bool(candidate.monitor_.converged)
        if not candidate_converged:
            _logger.warning(
                "regime_writer.hmm_not_converged_retry",
                symbol=symbol,
                tf=tf,
                n_iter=n_iter,
                seed=seed,
            )
            retry_model = GaussianHMM(
                n_components=n_components,
                covariance_type=eff_cov_type,
                n_iter=n_iter * 2,
                random_state=seed,
            )
            retry_model.fit(obs_matrix)
            if retry_model.monitor_.converged:
                candidate = retry_model
                candidate_converged = True
            else:
                _logger.warning(
                    "regime_writer.hmm_not_converged_final",
                    symbol=symbol,
                    tf=tf,
                    n_iter=n_iter * 2,
                    seed=seed,
                )

        # At n_restarts=1 (APR default) there is exactly one candidate and it is
        # unconditionally kept -- skip the O(len(obs_matrix)) scoring pass entirely,
        # since the comparison below would never actually run. Saves one full
        # forward-algorithm pass per symbol/tf cell at the shipped default, with no
        # behavior change (still byte-identical to the pre-todo-108 single-seed path).
        if n_restarts == 1:
            model = candidate
            converged = candidate_converged
            break

        candidate_ll = float(candidate.score(obs_matrix))

        # Prefer any converged candidate over any non-converged one; among candidates
        # with the same convergence status, keep the highest log-likelihood. Booleans
        # compare as 0/1 in Python, so this tuple comparison always ranks convergence
        # ahead of log-likelihood.
        if model is None or (candidate_converged, candidate_ll) > (converged, best_ll):
            model = candidate
            converged = candidate_converged
            best_ll = candidate_ll

    # Log HMM convergence iteration count for todo 226 (n_iter=200 headroom check).
    # NOTE: model.monitor_.converged is always True after hmmlearn's fit() completes
    # (it only exits when iter == n_iter OR tolerance is met, never partway through).
    # The real cap-hit signal for analysts is iters_used == n_iter_cap, not the converged
    # field — see hmmlearn 0.3.3 ConvergenceMonitor source for details.
    _logger.info(
        "regime_writer.hmm_convergence_iters",
        symbol=symbol,
        tf=tf,
        iters_used=int(model.monitor_.iter),
        n_iter_cap=int(model.monitor_.n_iter),
        converged=converged,
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
    log_emit = _compute_log_emit(obs_matrix, model.means_, model.covars_, eff_cov_type)

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
    bullish_states, ranging_states, bearish_states = _state_groups(label_map)
    p_up_list, p_ranging_list, p_down_list, prob_val_list, entropy_val_list = (
        _alpha_history_to_regime_probs(
            alpha_history, bullish_states, ranging_states, bearish_states
        )
    )

    # P2c hmm_churn — rolling label-change rate over the prior churn_window bars.
    # Computed on the actual mapped labels (not raw state indices) so it stays
    # correct even when n_components > 5 lets two distinct states share a label.
    labels_seq = [label_map[int(s)] for s in smoothed_states]
    churn_values = _compute_hmm_churn(labels_seq, churn_window)

    # Explicit loop — required for the stateful duration counter (alpha-derived
    # probabilities are already vectorized above via _alpha_history_to_regime_probs).
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
        update_rows.append(
            (
                label_map[state_idx],
                p_up_list[i],
                p_ranging_list[i],
                p_down_list[i],
                prob_val_list[i],
                entropy_val_list[i],
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
                # Ordered tuple, not a set, because bulk_update_by_key's `rows` param
                # requires (*set_cols, *key_cols) positional order -- see the
                # docstring on the fitting function above:
                # (regime, p_up, p_ranging, p_down, prob_val, entropy_val,
                # duration, hmm_churn, symbol, tf, ts). Imported from
                # feature_vector_persistence.py (Ring 1) rather than hand-typed
                # here so this ownership list can never drift from the one
                # feature_vector_persistence.py excludes from --refresh's
                # DO UPDATE SET -- both now derive from the same source of truth.
                set_cols=list(REGIME_WRITER_OWNED_COLUMN_NAMES),
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

    Opens its own psycopg connection for OHLCV reads only. Runs HMM compute
    and returns update_rows to the main process; never writes to the DB.

    Args:
        args: (symbol, tfs, dsn, n_components, vol_window, momentum_window,
               vol_of_vol_window, n_iter, hmm_random_state, covariance_type,
               min_hold_bars, heldout_fraction, full_cov_min_obs,
               min_state_occupation, churn_window, min_obs_factor, n_restarts,
               walk_forward_enabled, walk_forward_params)

        walk_forward_enabled (todo 248, APR: alpha.hmm.walk_forward.enabled,
            default False): when True, every tf routes through
            `_compute_symbol_tf_walk_forward` instead of `_compute_symbol_tf`'s
            single full-series fit -- see that function's docstring for the
            precondition this requires at the deployment level (only run against
            a freshly-recomputed corpus, never as a partial re-run over rows a
            prior single-fit pass already populated).
        walk_forward_params: dict[str, tuple[int, int]] mapping tf ->
            (refit_every_bars, initial_warmup_bars), tf-calibrated (APR:
            alpha.hmm.walk_forward.refit_every_bars.<tf> /
            .initial_warmup_bars.<tf>) since bars-per-refit-window is the
            actionable variable behind the pilot's cross-tf stability finding
            (docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md's broadened
            results). Only consulted when walk_forward_enabled is True.

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
        min_obs_factor,
        n_restarts,
        walk_forward_enabled,
        walk_forward_params,
    ) = args

    setup_service_logging("logs/regime_writer.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg.connect(dsn, options="-c idle_in_transaction_session_timeout=0")

        for tf in tfs:
            try:
                if walk_forward_enabled:
                    refit_every_bars, initial_warmup_bars = walk_forward_params[tf]
                    result = _compute_symbol_tf_walk_forward(
                        conn=conn,
                        symbol=symbol,
                        tf=tf,
                        n_components=n_components,
                        vol_window=vol_window,
                        n_iter=n_iter,
                        hmm_random_state=hmm_random_state,
                        momentum_window=momentum_window,
                        vol_of_vol_window=vol_of_vol_window,
                        refit_every_bars=refit_every_bars,
                        initial_warmup_bars=initial_warmup_bars,
                        covariance_type=covariance_type,
                        min_hold_bars=min_hold_bars,
                        full_cov_min_obs=full_cov_min_obs,
                        min_state_occupation=min_state_occupation,
                        churn_window=churn_window,
                        min_obs_factor=min_obs_factor,
                    )
                else:
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
                        min_obs_factor=min_obs_factor,
                        n_restarts=n_restarts,
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
            _conn = psycopg.connect(
                dsn,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                cfg = _load_config_service_shared(_conn)
                n_components = int(cfg.get_sync("feature.hmm.n_components", 3))
                vol_window = int(cfg.get_sync("feature.hmm.vol_window", 20))
                n_iter = int(cfg.get_sync("feature.hmm.n_iter", 200))
                hmm_random_state = int(cfg.get_sync("alpha.hmm.random_state", 42))
                n_restarts = int(cfg.get_sync("alpha.hmm.n_restarts", 1))
                momentum_window = int(cfg.get_sync("feature.hmm.obs_momentum_window", 20))
                vol_of_vol_window = int(cfg.get_sync("feature.hmm.obs_vol_of_vol_window", 20))
                covariance_type = cfg.get_sync("feature.hmm.covariance_type", "full")
                min_hold_bars = int(cfg.get_sync("feature.hmm.min_hold_bars", 3))
                heldout_fraction = float(cfg.get_sync("feature.hmm.heldout_fraction", 0.2))
                full_cov_min_obs = int(cfg.get_sync("feature.hmm.full_cov_min_obs", 500))
                min_state_occupation = float(cfg.get_sync("feature.hmm.min_state_occupation", 0.05))
                churn_window = int(cfg.get_sync("feature.hmm.churn_window", 10))
                min_obs_factor = int(
                    cfg.get_sync("feature.hmm.min_obs_factor", _MIN_OBS_FACTOR_DEFAULT)
                )

                # todo 248: walk-forward parameter-lookahead fix. Defaults to False --
                # landing this code must not itself change any existing regime label;
                # flipping this on (then running --refit) is a separate, later,
                # explicit deployment decision per the todo's own "genuine sequencing
                # decision" framing, not something this migration's seed value forces.
                walk_forward_enabled = bool(cfg.get_sync("alpha.hmm.walk_forward.enabled", False))
                # Per-tf (refit_every_bars, initial_warmup_bars) -- see
                # _WALK_FORWARD_DEFAULT_PARAMS' own docstring/comment above for the
                # full per-tf provenance and certainty caveats.
                walk_forward_params: dict[str, tuple[int, int]] = {
                    tf_key: (
                        int(
                            cfg.get_sync(
                                f"alpha.hmm.walk_forward.refit_every_bars.{tf_key}",
                                _WALK_FORWARD_DEFAULT_PARAMS[tf_key][0],
                            )
                        ),
                        int(
                            cfg.get_sync(
                                f"alpha.hmm.walk_forward.initial_warmup_bars.{tf_key}",
                                _WALK_FORWARD_DEFAULT_PARAMS[tf_key][1],
                            )
                        ),
                    )
                    for tf_key in _WALK_FORWARD_DEFAULT_PARAMS
                }

                symbols = args.symbols if args.symbols else _discover_symbols(_conn)
                tfs: list[str] = args.tf

                n_workers = args.workers
                if n_workers is None:
                    n_workers = int(cfg.get_sync("infra.regime_writer.workers", 1))
                # todo 216: BLAS thread cap, see make_worker_pool()/limit_blas_threads().
                blas_threads_per_worker = int(cfg.get_sync("infra.blas_threads_per_worker", 1))
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
                n_restarts=n_restarts,
                walk_forward_enabled=walk_forward_enabled,
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
                    min_obs_factor,
                    n_restarts,
                    walk_forward_enabled,
                    walk_forward_params,
                )
                for symbol in symbols
            ]

            # Pre-compile the JIT in the main process before spawning workers.
            # With cache=True the compile writes __pycache__ once; workers then load
            # the artifact read-only — no concurrent compile, no file-lock race.
            _jit_emit = np.zeros((10, n_components), dtype=np.float64)
            _jit_log_A = np.log(np.full((n_components, n_components), 1.0 / n_components))
            _jit_pi0 = np.full(n_components, 1.0 / n_components)
            _alpha_pass_jit(_jit_emit, _jit_log_A, _jit_pi0)
            _logger.info("regime_writer.jit_ready", n_components=n_components)

            total_updated = 0
            failures: list[str] = []

            write_conn = psycopg.connect(
                dsn,
                options="-c idle_in_transaction_session_timeout=0",
            )
            try:
                with _make_worker_pool(n_workers, blas_threads_per_worker) as pool:
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
