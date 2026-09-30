"""Walk-forward HMM math for the regime kernels (moved from services/regime_writer.py, 186-13).

Pure functions over arrays: the observation matrices, the causal forward filter and smoother,
the label maps, and the walk-forward fit-and-decode loop, plus the two declarations every
caller shares: `HmmConfig` (every APR key the kernels read, with its default) and the per-family
`RegimeFamilySpec` spec table. `kernels/regime.py` wraps them as registry kernels;
`services/regime_writer.py` re-imports the moved names so existing callers keep working. The
leading underscore keeps `discover_kernels` from treating this module as a kernel origin.

CORRECTNESS INVARIANTS (unchanged by the move):
- Decoding uses the forward filter only; `model.predict()` (Viterbi) leaks the future.
- Each (symbol, tf) series gets its own independent fit; each walk-forward segment's model is
  fit on the observations before its refit boundary only.
- Labels are mapped by emission mean[:, 0] rank onto a fixed vocabulary.
"""

from __future__ import annotations

import contextlib
import dataclasses
import math
import threading
import typing
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit

# Label-affecting numerics carried over verbatim from the pre-186 writer; the kernels read them
# from APR through `HmmConfig` (`alpha.hmm.covariance_ridge`, `alpha.hmm.momentum_vol_floor`,
# migration 411) and never fall back to these. They remain only as the defaults of the legacy
# helpers the analysis pilots call (`_build_obs_matrix`, `_log_emit_full`, `_compute_log_emit`),
# which 186-16 deletes with the pilots. 1e-300 (the log and variance floors below) is a mathematical guard against log(0) and
# division by zero, not a tunable, and N_NUMERIC_COLUMNS is a schema identifier; both stay
# constants.
_DEFAULT_COVARIANCE_RIDGE = 1e-6
_DEFAULT_MOMENTUM_VOL_FLOOR = 1e-8

# Rows per block of the obs-builder rolling reductions: bounds transient memory, never changes
# output (tests pin bit equality at every block size), so a default is safe here. Callers read
# `infra.hmm.rolling_block_rows` and pass it to the kernels as an argument; this is the fallback
# when they do not.
ROLLING_BLOCK_ROWS_KEY = "infra.hmm.rolling_block_rows"
DEFAULT_ROLLING_BLOCK_ROWS = 16384

# Canonical regime label set — no other values written to DB.
_LABEL_TRENDING_UP = "trending_up"
_LABEL_TRENDING_DOWN = "trending_down"
_LABEL_RANGING = "ranging"
_LABEL_TRANSITION_UP = "transition_up"
_LABEL_TRANSITION_DOWN = "transition_down"

# Volatility-only regime label set (Phase 172) - these three strings must match the
# `controlled_vocabulary` codes seeded for the `regime_volatility` namespace (migration
# 307_regime_volatility_schema_apr_cvr.sql). No other values written to
# feature_vectors.regime_volatility.
_LABEL_CALM = "calm"
_LABEL_ELEVATED = "elevated"
_LABEL_TURBULENT = "turbulent"

# Vocabulary mappings keyed on rank slots, threaded through `_build_label_map` /
# `_state_groups_by_vocab`. `_TREND_VOCAB` preserves the exact existing trend-label
# assignment; `_VOLATILITY_VOCAB` deliberately has no "low_mid"/"high_mid" slot -
# 171-FINAL-VERDICT.md section 5 validates only K=2 and K=3 for this axis, where
# `_build_label_map`'s `n_components >= 4` branch never fires, so a transition concept
# would be a slot with no meaning.
_TREND_VOCAB: dict[str, str] = {
    "low": _LABEL_TRENDING_DOWN,
    "high": _LABEL_TRENDING_UP,
    "low_mid": _LABEL_TRANSITION_DOWN,
    "high_mid": _LABEL_TRANSITION_UP,
    "mid": _LABEL_RANGING,
}
_VOLATILITY_VOCAB: dict[str, str] = {
    "low": _LABEL_CALM,
    "high": _LABEL_TURBULENT,
    "mid": _LABEL_ELEVATED,
}


# ---------------------------------------------------------------------------
# The one declaration of the HMM parameters
# ---------------------------------------------------------------------------

WALK_FORWARD_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1h", "1d")


# `threadpool_limits` changes the BLAS thread count of the whole process and restores the value it
# saw on entry, so two threads pinning and restoring it interleave (one restores while the other
# is mid-fit, or saves the other's pinned value). The heavy fit therefore runs one thread at a
# time. Reentrant, so a nested call in the same thread cannot deadlock. The ProcessPool writer
# has one caller per process, so the lock is never contended there.
_BLAS_PIN_LOCK = threading.RLock()


@contextlib.contextmanager
def pinned_blas_threads() -> Iterator[None]:
    """Run the body with BLAS at one thread, serialized against other threads doing the same."""
    with _BLAS_PIN_LOCK, threadpool_limits(limits=1):
        yield


def _apr(key: str) -> dict[str, str]:
    return {"apr_key": key}


@dataclass(frozen=True)
class HmmConfig:
    """Every APR-backed value the regime kernels read: field name and APR key, declared once.
    The loader (`from_values`), the golden capture, the writer and the rebuild all read this
    class; `FeatureFactoryConfig.hmm` carries one (the registry hands kernels that config).

    There are no defaults, on purpose: every one of these values changes stored labels (each
    fit is path dependent), and the live APR values differ from the values an old default would
    have been (n_components 5, volatility windows 250), so a missing key raises and names the
    key instead of silently running a different model. The annotation is the cast applied to the
    APR value. `infra.hmm.rolling_block_rows` is not a field because it does not change output
    (`ROLLING_BLOCK_ROWS_KEY`; callers pass it to the kernels as an argument and a default is
    safe there).

    Per-tf schedule (`alpha.hmm.walk_forward.*`, todo 248): (refit_every_bars,
    initial_warmup_bars). 1h is the pilot's directly-measured value (1650, 3300); 15m is the
    broadened pilot's own independently-confirmed value (same schedule, 4x bar density); 5m
    scales the same schedule by its own 12x density ratio (not independently piloted); 1d is a
    fresh, unpiloted ~1yr-refit/~2yr-warmup estimate at daily bar density. See
    docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md for the full derivation and per-tf
    certainty caveats.
    """

    hmm_n_components: int = field(metadata=_apr("feature.hmm.n_components"))
    hmm_vol_window: int = field(metadata=_apr("feature.hmm.vol_window"))
    hmm_momentum_window: int = field(metadata=_apr("feature.hmm.obs_momentum_window"))
    hmm_vol_of_vol_window: int = field(metadata=_apr("feature.hmm.obs_vol_of_vol_window"))
    hmm_n_iter: int = field(metadata=_apr("feature.hmm.n_iter"))
    hmm_random_state: int = field(metadata=_apr("alpha.hmm.random_state"))
    hmm_covariance_type: str = field(metadata=_apr("feature.hmm.covariance_type"))
    hmm_min_hold_bars: int = field(metadata=_apr("feature.hmm.min_hold_bars"))
    hmm_full_cov_min_obs: int = field(metadata=_apr("feature.hmm.full_cov_min_obs"))
    hmm_min_state_occupation: float = field(metadata=_apr("feature.hmm.min_state_occupation"))
    hmm_churn_window: int = field(metadata=_apr("feature.hmm.churn_window"))
    # Minimum obs rows per (symbol, tf) = n_components * this factor; below it the fit is
    # meaningless (too few state transitions to estimate A). Migration 275, todo 009 Part A.
    hmm_min_obs_factor: int = field(metadata=_apr("feature.hmm.min_obs_factor"))
    hmm_covariance_ridge: float = field(metadata=_apr("alpha.hmm.covariance_ridge"))
    hmm_momentum_vol_floor: float = field(metadata=_apr("alpha.hmm.momentum_vol_floor"))
    hmm_volatility_n_components: int = field(metadata=_apr("alpha.hmm_volatility.n_components"))
    hmm_volatility_vol_window: int = field(metadata=_apr("alpha.hmm_volatility.vol_window"))
    hmm_volatility_vol_of_vol_window: int = field(
        metadata=_apr("alpha.hmm_volatility.vol_of_vol_window")
    )
    hmm_volatility_covariance_type: str = field(
        metadata=_apr("alpha.hmm_volatility.covariance_type")
    )
    hmm_refit_every_bars_5m: int = field(
        metadata=_apr("alpha.hmm.walk_forward.refit_every_bars.5m")
    )
    hmm_initial_warmup_bars_5m: int = field(
        metadata=_apr("alpha.hmm.walk_forward.initial_warmup_bars.5m")
    )
    hmm_refit_every_bars_15m: int = field(
        metadata=_apr("alpha.hmm.walk_forward.refit_every_bars.15m")
    )
    hmm_initial_warmup_bars_15m: int = field(
        metadata=_apr("alpha.hmm.walk_forward.initial_warmup_bars.15m")
    )
    hmm_refit_every_bars_1h: int = field(
        metadata=_apr("alpha.hmm.walk_forward.refit_every_bars.1h")
    )
    hmm_initial_warmup_bars_1h: int = field(
        metadata=_apr("alpha.hmm.walk_forward.initial_warmup_bars.1h")
    )
    hmm_refit_every_bars_1d: int = field(
        metadata=_apr("alpha.hmm.walk_forward.refit_every_bars.1d")
    )
    hmm_initial_warmup_bars_1d: int = field(
        metadata=_apr("alpha.hmm.walk_forward.initial_warmup_bars.1d")
    )

    @classmethod
    def apr_keys(cls) -> tuple[str, ...]:
        """Every APR key the loader reads."""
        return tuple(f.metadata["apr_key"] for f in dataclasses.fields(cls))

    @classmethod
    def from_values(cls, get: Callable[[str, Any], Any]) -> HmmConfig:
        """From `get(key, default)`: `ConfigService.get_sync` for a live load, a dict lookup for a
        stored snapshot, a recording wrapper to capture the snapshot. A key whose value is missing
        (None) raises KeyError naming it; no value is ever defaulted."""
        hints = typing.get_type_hints(cls)
        values: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            key = f.metadata["apr_key"]
            raw = get(key, None)
            if raw is None:
                raise KeyError(
                    f"regime HMM parameter {key!r} is missing from APR; it changes every stored "
                    "regime label, so there is no default (seed it in config_state)"
                )
            values[f.name] = hints[f.name](raw)
        return cls(**values)

    def walk_forward_schedule(self, tf: str) -> tuple[int, int]:
        """(refit_every_bars, initial_warmup_bars) for `tf`; ValueError outside 5m/15m/1h/1d."""
        if tf not in WALK_FORWARD_TIMEFRAMES:
            raise ValueError(
                f"walk-forward HMM schedule is defined for {WALK_FORWARD_TIMEFRAMES}, got {tf!r}"
            )
        return (
            int(getattr(self, f"hmm_refit_every_bars_{tf}")),
            int(getattr(self, f"hmm_initial_warmup_bars_{tf}")),
        )


def load_rolling_block_rows(get: Callable[[str, Any], Any]) -> int:
    """`infra.hmm.rolling_block_rows` from `get(key, default)`."""
    return int(get(ROLLING_BLOCK_ROWS_KEY, DEFAULT_ROLLING_BLOCK_ROWS))


# ---------------------------------------------------------------------------
# Core HMM functions
# ---------------------------------------------------------------------------


def _rolling(arr: np.ndarray, window: int, fn, block_rows: int | None = None) -> np.ndarray:
    """Apply fn over a sliding window, zero-padding the warm-up prefix.

    With `block_rows`, `fn` runs over that many windows at a time and the results are
    concatenated. `np.std` and `np.mean` allocate an (n_windows, window) float64 intermediate
    (about 790 MB at 395,609 rows and window 250); blocking bounds it to
    `block_rows * window * 8` bytes. Each output element is the same per-window reduction, so
    the result is bit-identical to the unblocked one (tests pin it); prefix-sum variants would
    change the bytes and are not used.
    """
    windows = np.lib.stride_tricks.sliding_window_view(arr, window)
    if block_rows is None or block_rows >= len(windows):
        return np.concatenate([np.zeros(window - 1), fn(windows, axis=1)])
    parts = [np.zeros(window - 1)]
    for start in range(0, len(windows), block_rows):
        parts.append(fn(windows[start : start + block_rows], axis=1))
    return np.concatenate(parts)


def _observations_trend(
    closes: np.ndarray,
    volumes: np.ndarray,
    vol_window: int,
    momentum_window: int,
    vol_of_vol_window: int,
    block_rows: int | None,
    momentum_vol_floor: float,
) -> tuple[np.ndarray, int]:
    """(obs_matrix, valid_start) of the trend family; see `_build_obs_matrix` for the columns.

    `valid_start` indexes the log-return series: obs row j is log-return row `valid_start + j`,
    which is bar row `valid_start + j + 1`. Insufficient input returns an empty matrix.
    """
    closes_arr = np.asarray(closes, dtype=float)
    volumes_arr = np.maximum(np.asarray(volumes, dtype=float), 1.0)  # guard zero volume

    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))
    log_volumes = np.log(volumes_arr[1:])  # aligned to log_returns

    if len(log_returns) < max(vol_window, momentum_window, vol_of_vol_window):
        return np.empty((0, 5), dtype=float), 0

    realized_vol = _rolling(log_returns, vol_window, np.std, block_rows)
    mom_raw = _rolling(log_returns, momentum_window, np.sum, block_rows)
    momentum = mom_raw / np.maximum(realized_vol, momentum_vol_floor)
    vol_of_vol = _rolling(realized_vol, vol_of_vol_window, np.std, block_rows)
    rolling_mean_logvol = _rolling(log_volumes, vol_window, np.mean, block_rows)
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
    return obs, valid_start


def _build_obs_matrix(
    timestamps: list,
    closes: list[float] | np.ndarray,
    volumes: list[float] | np.ndarray,
    vol_window: int,
    momentum_window: int,
    vol_of_vol_window: int,
    block_rows: int | None = None,
    momentum_vol_floor: float = _DEFAULT_MOMENTUM_VOL_FLOOR,
) -> tuple[np.ndarray, list]:
    """Build (n_valid, 5) observation matrix from OHLCV prices and volumes.

    Observation dimensions:
      [0] log_return   = ln(close[t] / close[t-1])
      [1] realized_vol = rolling std of log_returns over vol_window bars
      [2] momentum     = sum(log_returns[-momentum_window:]) / (realized_vol + eps)
                         Directional drift signal, vol-normalized; eps is the
                         `momentum_vol_floor` (`alpha.hmm.momentum_vol_floor`).
      [3] vol_of_vol   = rolling std of realized_vol over vol_of_vol_window bars
                         Regime transition indicator: stable regimes have stable vol.
      [4] rel_volume   = log(volume[t]) - rolling mean(log(volume), vol_window)
                         Volume anomaly relative to recent baseline.

    valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
    All rows before valid_start are discarded (insufficient window history).
    Returns (obs_matrix, valid_timestamps).
    """
    obs, valid_start = _observations_trend(
        np.asarray(closes, dtype=float),
        np.asarray(volumes, dtype=float),
        vol_window,
        momentum_window,
        vol_of_vol_window,
        block_rows,
        momentum_vol_floor,
    )
    if len(obs) == 0:
        return obs, []
    return obs, timestamps[1:][valid_start:]


def _observations_volatility(
    closes: np.ndarray,
    vol_window: int,
    vol_of_vol_window: int,
    block_rows: int | None = None,
) -> tuple[np.ndarray, int]:
    """(obs_matrix, valid_start) of the volatility family; see `_build_obs_matrix_volatility`
    for the columns and the start index. `valid_start` indexes the log-return series, as in
    `_observations_trend`. Insufficient input returns an empty matrix."""
    closes_arr = np.asarray(closes, dtype=float)

    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))

    if len(log_returns) < vol_window + vol_of_vol_window - 1:
        return np.empty((0, 2), dtype=float), 0

    realized_vol = _rolling(log_returns, vol_window, np.std, block_rows)
    vol_of_vol = _rolling(realized_vol, vol_of_vol_window, np.std, block_rows)

    valid_start = vol_window + vol_of_vol_window - 2
    obs = np.column_stack(
        [
            realized_vol[valid_start:],
            vol_of_vol[valid_start:],
        ]
    )
    return obs, valid_start


def _build_obs_matrix_volatility(
    timestamps: list,
    closes: list[float] | np.ndarray,
    vol_window: int,
    vol_of_vol_window: int,
    block_rows: int | None = None,
) -> tuple[np.ndarray, list]:
    """Build (n_valid, 2) observation matrix from close prices only: [realized_vol,
    vol_of_vol]. Phase 172's volatility-only regime axis -- the only axis that cleared
    the null-arm block-reliability control per 171-FINAL-VERDICT.md. Trend
    (log_return/momentum) and volume (rel_volume) columns are deliberately absent
    (dead on direct null-arm evidence), not pending.

    Observation dimensions:
      [0] realized_vol = rolling std of log_returns over vol_window bars.
                         Column 0 because `_build_label_map` ranks states by
                         means[:, 0] -- putting vol_of_vol first would give the
                         emitted labels a different meaning (calm/elevated/turbulent
                         must order by vol level, not by vol-of-vol).
      [1] vol_of_vol   = rolling std of realized_vol over vol_of_vol_window bars.

    Built directly from `closes`/`_rolling` rather than by slicing columns [1, 3] out
    of `_build_obs_matrix`'s 5-column result -- this skips the wasted
    momentum/rel_volume/log_return compute (rel_volume alone requires a separate
    rolling-mean-of-log-volume pass) and makes column-index confusion between the two
    matrices' different semantics impossible. `volumes` is never read.

    valid_start = vol_window + vol_of_vol_window - 2. This DIVERGES from
    `_build_obs_matrix`'s `max(windows) - 1`: that expression is correct for three
    columns computed by a single rolling pass over log_returns, but vol_of_vol is a
    rolling std of realized_vol, which `_rolling` itself zero-pads for its first
    vol_window - 1 entries. Under `max(windows) - 1`, the first vol_window - 1 emitted
    vol_of_vol values would be computed over windows that still contain those zeros --
    warmup artifacts presented as valid observations. `vol_window + vol_of_vol_window -
    2` is the first index at which the entire vol_of_vol lookback window lies inside
    real data, so no emitted vol_of_vol value is ever computed over a zero-padded
    realized_vol entry. At the seeded windows of 20/60 this discards 19 additional bars
    per cell out of a series of at least 20000 -- immaterial cost, no fabricated-input
    rows. `_build_obs_matrix` itself is NOT changed to match -- its 26.8M existing
    rows were produced under its current behavior, and editing it would silently
    change the meaning of a column this phase deliberately leaves untouched (filed as
    pending todo 286). Plan 172-01's null-arm gate measures the volatility axis
    through the composite matrix's columns 1 and 3 and therefore under the legacy
    start index; the 19-bar difference is not material to a block-reliability
    statistic computed over tens of thousands of bars, noted here rather than left for
    a future reader to notice the mismatch.

    Returns (obs_matrix, valid_timestamps). Insufficient input (fewer than
    vol_window + vol_of_vol_window - 1 log returns) returns
    (np.empty((0, 2)), []) rather than raising.
    """
    obs, valid_start = _observations_volatility(
        np.asarray(closes, dtype=float), vol_window, vol_of_vol_window, block_rows
    )
    if len(obs) == 0:
        return obs, []
    return obs, timestamps[1:][valid_start:]


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
    return np.asarray(
        -0.5 * np.sum(diff**2 / var_clipped[np.newaxis, :, :], axis=2)
        - 0.5 * np.sum(np.log(2 * np.pi * var_clipped), axis=1)[np.newaxis, :]
    )


def _log_emit_full(
    obs: np.ndarray,
    means: np.ndarray,
    covars: np.ndarray,
    ridge: float = _DEFAULT_COVARIANCE_RIDGE,
) -> np.ndarray:
    """Log emission (n, K) for full-covariance Gaussian. covars shape (K, d, d).

    Uses Cholesky decomposition for numerical stability. Regularizes with `ridge` * I
    (`alpha.hmm.covariance_ridge`) to guard near-singular covariance matrices (rare but
    possible on flat TFs). Falls back to diagonal on Cholesky failure per state.
    """
    n, d = obs.shape
    K = means.shape[0]
    log_emit = np.zeros((n, K))
    log_2pi_d = d * math.log(2 * math.pi)
    for k in range(K):
        diff = obs - means[k]  # (n, d)
        cov = covars[k] + np.eye(d) * ridge
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
    obs: np.ndarray,
    means: np.ndarray,
    covars: np.ndarray,
    cov_type: str,
    ridge: float = _DEFAULT_COVARIANCE_RIDGE,
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
        return _log_emit_full(obs, means, covars, ridge)
    d = means.shape[1]
    covars_diag = covars[:, np.arange(d), np.arange(d)] if covars.ndim == 3 else covars
    return _log_emit_diag(obs, means, covars_diag)


def _state_groups_by_vocab(
    label_map: dict[int, str], vocab: dict[str, str]
) -> tuple[list[int], list[int], list[int]]:
    """This model's low/mid/high STATE-INDEX sets, derived from its own label_map and
    the vocabulary that produced it. Meaningful only relative to THIS specific fit --
    state 2 in one independently-fit model has no relationship to state 2 in another
    (raw indices are not comparable across fits; see `_seed_prior_from_label`'s
    docstring).

    `low_states` collects state indices whose label is `vocab["low"]` or
    `vocab.get("low_mid")`; `high_states` collects `vocab["high"]` or
    `vocab.get("high_mid")`; `mid_states` collects `vocab["mid"]`.

    Returns (low_states, mid_states, high_states).
    """
    low_labels = {vocab["low"]}
    if "low_mid" in vocab:
        low_labels.add(vocab["low_mid"])
    high_labels = {vocab["high"]}
    if "high_mid" in vocab:
        high_labels.add(vocab["high_mid"])
    mid_label = vocab["mid"]

    low_states = [k for k, v in label_map.items() if v in low_labels]
    mid_states = [k for k, v in label_map.items() if v == mid_label]
    high_states = [k for k, v in label_map.items() if v in high_labels]
    return low_states, mid_states, high_states


def _state_groups(label_map: dict[int, str]) -> tuple[list[int], list[int], list[int]]:
    """This model's bullish/ranging/bearish STATE-INDEX sets, derived from its own
    label_map. Meaningful only relative to THIS specific fit -- state 2 in one
    independently-fit model has no relationship to state 2 in another (raw indices
    are not comparable across fits; see `_seed_prior_from_label`'s docstring).

    Thin wrapper over `_state_groups_by_vocab(label_map, _TREND_VOCAB)`, reordering
    the (low, mid, high) result to (high, mid, low) to preserve this function's
    documented (bullish_states, ranging_states, bearish_states) return contract
    exactly -- both existing callers pass positionally and a reorder here would
    silently invert probability mass.

    Returns (bullish_states, ranging_states, bearish_states).
    """
    low_states, mid_states, high_states = _state_groups_by_vocab(label_map, _TREND_VOCAB)
    return high_states, mid_states, low_states


def _alpha_history_to_regime_probs(
    alpha_history: np.ndarray,
    high_states: list[int],
    mid_states: list[int],
    low_states: list[int],
) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """Vectorized per-bar (p_high, p_mid, p_low, prob_val, entropy_val) from a
    segment's alpha vectors -- shared by `_compute_symbol_tf` and
    `_walk_forward_hmm_full`, both of which previously computed this identically
    via a per-bar Python loop (`sum(alpha[s] for s in states)` + per-bar np.max/
    np.sum/np.log calls). Operating on the whole (n, K) array at once instead of
    row-by-row is both less code and meaningfully cheaper at corpus scale (tens of
    thousands of bars per segment).

    Parameter names are vocab-agnostic (`high_states`/`mid_states`/`low_states`, not
    `bullish_states`/`ranging_states`/`bearish_states`) so this function carries no
    trend-semantic vocabulary -- it is shared by both the trend and volatility label
    paths. Existing callers pass all three positionally (verified via
    `grep -n '_alpha_history_to_regime_probs' services/regime_writer.py`; none uses
    keyword arguments), so this rename requires zero call-site edits.

    alpha_history: shape (n, K), one row per bar.
    Returns 5 lists, each length n, index-aligned to alpha_history's rows.
    """
    p_high = (
        alpha_history[:, high_states].sum(axis=1) if high_states else np.zeros(len(alpha_history))
    )
    p_mid = alpha_history[:, mid_states].sum(axis=1) if mid_states else np.zeros(len(alpha_history))
    p_low = alpha_history[:, low_states].sum(axis=1) if low_states else np.zeros(len(alpha_history))
    prob_val = alpha_history.max(axis=1)
    entropy_val = -np.sum(alpha_history * np.log(np.maximum(alpha_history, 1e-300)), axis=1)
    return (
        p_high.tolist(),
        p_mid.tolist(),
        p_low.tolist(),
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


# Compat alias — function was renamed from _causal_decode to _alpha_pass
_causal_decode = _alpha_pass


def _smooth_states(raw_states: np.ndarray, min_hold: int) -> np.ndarray:
    """Minimum holding-period smoother. Requires min_hold consecutive bars of the same
    new state before confirming a transition. Causal — no look-ahead.

    Row t confirms the raw state when the last `min_hold` raw states (t - min_hold + 1 .. t)
    are all equal, which needs t >= min_hold; the output holds the last confirmed state, or
    the first raw state before any confirmation. Computed from run lengths in integers
    (a run of length >= min_hold ending at t is exactly that window test), so the result is
    identical to the per-row window loop it replaced (tests keep that loop as the reference).
    """
    if min_hold <= 1 or len(raw_states) == 0:
        return raw_states.copy()
    n = len(raw_states)
    index = np.arange(n)
    run_start = np.maximum.accumulate(
        np.where(np.concatenate([[True], raw_states[1:] != raw_states[:-1]]), index, 0)
    )
    confirmed = (index - run_start + 1 >= min_hold) & (index >= min_hold)
    last_confirmed = np.maximum.accumulate(np.where(confirmed, index, -1))
    return np.where(last_confirmed >= 0, raw_states[np.maximum(last_confirmed, 0)], raw_states[0])


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
    min_state = min(occupation, key=lambda state: occupation[state])
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
    if churn_window < 1:
        raise ValueError(f"churn_window must be >= 1, got {churn_window}")
    n = len(labels)
    if n == 0:
        return np.zeros(0, dtype=float)

    labels_arr = np.asarray(labels)
    changes = np.zeros(n, dtype=float)
    if n > 1:
        changes[1:] = (labels_arr[1:] != labels_arr[:-1]).astype(float)

    # Sums of 0/1 flags are exact integers in float64, so the window sum from the cumulative
    # sum and the division by the window's bar count give the same bits as np.mean over the
    # slice did.
    cumulative = np.cumsum(changes)
    window_sum = cumulative.copy()
    window_sum[churn_window:] -= cumulative[:-churn_window]
    bars_available = np.minimum(np.arange(1, n + 1), churn_window).astype(float)
    return np.asarray(window_sum / bars_available)


def _build_label_map(means: np.ndarray, vocab: dict[str, str] | None = None) -> dict[int, str]:
    """Map integer HMM states to canonical regime text labels, drawn from `vocab`.

    Sorted deterministically by fitted emission mean[:, 0] -- the ordering dimension is
    column 0 of whatever observation matrix produced `means`, which is `log_return` for
    the trend matrix (`_build_obs_matrix`) and `realized_vol` for the volatility matrix
    (`_build_obs_matrix_volatility`). Assignment by rank:

      K=2: order[0]->vocab["low"], order[1]->vocab["high"]
      K=3: order[0]->vocab["low"], order[2]->vocab["high"], order[1]->vocab["mid"]
      K=4: order[0]->vocab["low"], order[3]->vocab["high"],
           order[1]->vocab["mid"], order[2]->vocab["mid"] (via the "low_mid"/"high_mid"
           branch below when present in vocab)
      K=5: order[0]->vocab["low"], order[4]->vocab["high"],
           order[1]->vocab["low_mid"], order[3]->vocab["high_mid"], order[2]->vocab["mid"]
      K>5: extremes get vocab["low"]/vocab["high"], next-inward get
           vocab["low_mid"]/vocab["high_mid"], all remaining middle states get
           vocab["mid"].

    This produces semantically stable labels regardless of which integer hmmlearn
    assigns to which state.

    Args:
        means: Shape (K, n_features) -- emission means from fitted HMM. Column 0 is
            the ordering dimension used for sorting.
        vocab: rank-slot -> label string mapping (`_TREND_VOCAB` or
            `_VOLATILITY_VOCAB`). Defaults to `_TREND_VOCAB`, so the four existing
            trend-path call sites (`_walk_forward_hmm_labels`, `_walk_forward_hmm_full`,
            `_hmm_seed_stability_check`, and the single-fit path inside
            `_compute_symbol_tf`) need zero edits and remain byte-identical to today's
            behavior.

    Returns:
        dict mapping integer state index -> canonical text label.

    Raises:
        ValueError: if `n_components >= 4` and `vocab` has no "low_mid"/"high_mid"
            slot -- `_VOLATILITY_VOCAB` deliberately has no transition concept and only
            supports K=2/K=3 (171-FINAL-VERDICT.md section 5).
    """
    vocab = vocab if vocab is not None else _TREND_VOCAB
    n_components = means.shape[0]
    means_ret = means[:, 0]  # ordering dimension
    order = np.argsort(means_ret)  # ascending: [lowest, ..., highest]
    label_map: dict[int, str] = {}

    # Extremes are always the low/high labels.
    label_map[int(order[0])] = vocab["low"]
    label_map[int(order[-1])] = vocab["high"]

    if n_components >= 4:
        if "low_mid" not in vocab or "high_mid" not in vocab:
            missing = [k for k in ("low_mid", "high_mid") if k not in vocab]
            raise ValueError(
                f"_build_label_map: n_components={n_components} requires a vocabulary "
                f"with 'low_mid'/'high_mid' slots, but vocab is missing {missing}. This "
                "vocabulary supports only K=2 and K=3."
            )
        # Second from each extreme are transition states
        label_map[int(order[1])] = vocab["low_mid"]
        label_map[int(order[-2])] = vocab["high_mid"]

    # All remaining middle states get the mid label.
    for i in range(n_components):
        if i not in label_map:
            label_map[i] = vocab["mid"]

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
    return np.asarray(pi0 / pi0.sum())


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
    vocab: dict[str, str] | None = None,
    *,
    min_obs_factor: int,
    covariance_ridge: float,
) -> list[dict[str, Any]]:
    """Production-parity walk-forward decode (todo 248): per-segment version of
    `_walk_forward_hmm_labels` that additionally returns the per-bar alpha vectors,
    each segment's own convergence status, and each segment's own degenerate-occupation
    gate result -- everything `walk_forward_family_arrays` needs to assemble
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

    `vocab` (Phase 172): rank-slot label vocabulary passed through to `_build_label_map`
    and `_state_groups_by_vocab` for every segment's own fit. Defaults to `_TREND_VOCAB`
    (resolved internally when the caller passes/omits None), so every existing positional
    and keyword call site -- including the Gate 4 pilot scripts and this function's own
    pre-172 tests -- reproduces today's trend-path output exactly, unchanged. Passing
    `_VOLATILITY_VOCAB` restricts each segment's labels to the calm/elevated/turbulent set.

    Causality (todo 451, 186-13): a segment's degenerate/non-converged verdict is computed at its
    refit boundary from data before it. The fitted model decodes its own training slice from
    the stationary prior, the decode is smoothed with `min_hold_bars`, and
    `_check_occupation_gate` runs on that (`gate_info["gate_basis"] == "training_slice"`).
    Gating on the decoded segment, as this function first did, let bars up to
    `refit_every_bars` ahead decide whether bar t is written. The first boundary is
    `max(initial_warmup_bars, n_components * min_obs_factor)`, independent of the series
    length, and a series with no boundary returns no segments (no ValueError): whether early
    rows get labels must not depend on how many rows come later.

    Returns one dict per refit segment (NOT one dict per bar), each:
        {
            "seg_start": int, "seg_end": int,  # half-open [seg_start, seg_end) bar-index
                range into obs_matrix / valid_ts (both 1:1 index-aligned by construction)
            "states": np.ndarray[int],  # smoothed state index per bar, len == seg_end - seg_start
            "state_labels": tuple[str, ...],  # label of state k, from this segment's own fit
                (a bar's label is `state_labels[states[i]]`; two states can share a label at
                K >= 4, so run lengths and churn count label changes, not state changes)
            "p_up": list[float], "p_ranging": list[float], "p_down": list[float],
                # probability mass on this segment's HIGH/MID/LOW state groups (per its
                # own vocab, via _state_groups_by_vocab) -- for _TREND_VOCAB these are
                # trending_up/ranging/trending_down; for _VOLATILITY_VOCAB they are
                # turbulent/elevated/calm. Key names are unchanged from before Phase 172
                # (renaming them would touch the legacy path and its tests for no
                # functional gain) but their meaning is now vocab-relative.
            "prob_val": list[float], "entropy_val": list[float],  # same length, one
                per bar -- computed here (not by the caller) because bullish/ranging/
                bearish STATE-INDEX membership is only meaningful relative to THIS
                segment's own `label_map` (state 2 in one segment's independently-fit
                model has no relationship to state 2 in the next segment's model);
                exposing raw alpha + a bare label_map to the caller would just move
                this same per-segment index resolution into the caller for no benefit.
            "converged": bool,
            "iters_used": int, "n_iter_cap": int,  # the fit's EM iterations and its cap
            "is_degenerate": bool,     # _check_occupation_gate's verdict for this segment
            "gate_info": dict,         # _check_occupation_gate's diagnostics for this segment
        }
    Degenerate/non-converged segments ARE included (not silently dropped) -- this
    function is a pure reporter of what each segment's fit produced; the caller
    (`walk_forward_family_arrays`) decides whether to write a segment's bars,
    mirroring the existing separation between `_check_occupation_gate` (decides) and
    `_compute_symbol_tf` (acts on the decision) in the single-fit path.
    """
    vocab = vocab if vocab is not None else _TREND_VOCAB
    n = len(obs_matrix)

    segment_results: list[dict[str, Any]] = []
    boundary = max(initial_warmup_bars, n_components * min_obs_factor)
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
        # hmmlearn 0.3.3's monitor_.converged is always True after fit() completes
        # (ConvergenceMonitor.converged's first disjunct is `iter == n_iter`, which is
        # trivially satisfied whenever the EM loop runs to its cap) -- iter < n_iter is
        # the only signal that distinguishes a genuine tolerance-convergence from a
        # cap-hit (todo 229, proven exact against hmmlearn 0.3.3's fit() loop).
        converged = model.monitor_.iter < model.monitor_.n_iter
        if not converged:
            retry_model = GaussianHMM(
                n_components=n_components,
                covariance_type=eff_cov_type,
                n_iter=n_iter * 2,
                random_state=hmm_random_state,
            )
            retry_model.fit(train_scaled)
            if retry_model.monitor_.iter < retry_model.monitor_.n_iter:
                model = retry_model
                converged = True

        seg_end = min(boundary + refit_every_bars, n)

        label_map = _build_label_map(model.means_, vocab=vocab)

        stationary_prior = _stationary_distribution(model.transmat_)
        if prior_label is None:
            pi0 = stationary_prior
        else:
            pi0 = _seed_prior_from_label(label_map, prior_label, n_components, stationary_prior)

        seg_scaled = scaler.transform(obs_matrix[boundary:seg_end])
        log_emit = _compute_log_emit(
            seg_scaled, model.means_, model.covars_, eff_cov_type, covariance_ridge
        )
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
        raw_states, alpha_history = _alpha_pass_jit(log_emit, log_A, pi0)
        smoothed = _smooth_states(raw_states, min_hold_bars)
        state_labels = tuple(label_map[k] for k in range(n_components))

        # The gate sees the model's own training slice, not the segment it is about to label
        # (see the Causality paragraph in the docstring).
        # A non-converged fit is refused by the gate after its length checks and before it reads
        # any state, so only the slice length is needed and the decode is skipped.
        if converged:
            train_log_emit = _compute_log_emit(
                train_scaled, model.means_, model.covars_, eff_cov_type, covariance_ridge
            )
            train_raw, _ = _alpha_pass_jit(train_log_emit, log_A, stationary_prior)
            train_smoothed = _smooth_states(train_raw, min_hold_bars)
        else:
            train_smoothed = np.empty(len(train_scaled), dtype=np.int64)
        is_degenerate, gate_info = _check_occupation_gate(
            train_smoothed, n_components, min_state_occupation, converged
        )
        gate_info = {**gate_info, "gate_basis": "training_slice"}

        # This segment's own state groups, derived from its own label_map -- see
        # _state_groups' docstring for why raw state indices aren't comparable
        # across independently-fit segments. Deliberate reorder: _state_groups_by_vocab
        # returns (low, mid, high); _alpha_history_to_regime_probs's positional contract
        # is (high, mid, low) -- this call site reproduces _state_groups' own historical
        # (bullish, ranging, bearish) argument order exactly, so the trend path's
        # probability assignment (p_up=bullish mass, p_down=bearish mass) is unchanged.
        # Getting this reorder wrong silently inverts probability mass; see this file's
        # equivalence test (no-vocab output must match pre-172 behavior byte-for-byte)
        # and the swap-and-confirm-red check in the volatility mean-p_up test.
        low_states, mid_states, high_states = _state_groups_by_vocab(label_map, vocab)
        p_up_list, p_ranging_list, p_down_list, prob_val_list, entropy_val_list = (
            _alpha_history_to_regime_probs(alpha_history, high_states, mid_states, low_states)
        )

        segment_results.append(
            {
                "seg_start": boundary,
                "seg_end": seg_end,
                "states": smoothed,
                "state_labels": state_labels,
                "p_up": p_up_list,
                "p_ranging": p_ranging_list,
                "p_down": p_down_list,
                "prob_val": prob_val_list,
                "entropy_val": entropy_val_list,
                "converged": converged,
                "iters_used": int(model.monitor_.iter),
                "n_iter_cap": int(model.monitor_.n_iter),
                "is_degenerate": is_degenerate,
                "gate_info": gate_info,
            }
        )
        prior_label = state_labels[int(smoothed[-1])]
        boundary = seg_end

    return segment_results


def _hmm_seed_stability_check(
    obs_matrix: np.ndarray,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    seeds: list[int],
    full_cov_min_obs: int,
    vocab: dict[str, str] | None = None,
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

    `vocab` defaults to None, which `_build_label_map` resolves to `_TREND_VOCAB` (existing
    behavior, unchanged). Pass `_VOLATILITY_VOCAB` to run this same diagnostic against a
    volatility-axis obs_matrix (Phase 172 code review WR-02) -- without this, a future caller
    pointing this diagnostic at a volatility fit would get labels silently drawn from the
    wrong vocabulary.

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

        label_map = _build_label_map(model.means_, vocab=vocab)
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
# The family specs and the one walk-forward family function (186-13)
# ---------------------------------------------------------------------------

TREND_LABELS: tuple[str, ...] = (
    _LABEL_TRENDING_UP,
    _LABEL_TRENDING_DOWN,
    _LABEL_RANGING,
    _LABEL_TRANSITION_UP,
    _LABEL_TRANSITION_DOWN,
)
VOLATILITY_LABELS: tuple[str, ...] = (_LABEL_CALM, _LABEL_ELEVATED, _LABEL_TURBULENT)

FAMILY_TREND = "trend"
FAMILY_VOLATILITY = "volatility"

# Numeric columns per family: three state-group probabilities, hmm_regime_prob, hmm_entropy,
# hmm_duration, hmm_churn. A schema identifier (the owned-column tuples in
# feature_vector_persistence), checked against them below, not a tunable.
N_NUMERIC_COLUMNS = 7

# segment_status codes: 0 no model yet, 1 written, 2 degenerate_occupation, 3 not_converged,
# 4 any other gate reason.
STATUS_NO_MODEL = 0.0
STATUS_WRITTEN = 1.0
STATUS_DEGENERATE_OCCUPATION = 2.0
STATUS_NOT_CONVERGED = 3.0
STATUS_OTHER_GATE = 4.0

_GATE_REASON_STATUS = {
    "degenerate_occupation": STATUS_DEGENERATE_OCCUPATION,
    "not_converged": STATUS_NOT_CONVERGED,
}


# Event kinds a run reports (the kernel is silent; the caller logs them with its own context,
# symbol and tf, under the names operators grep for). The skipped-segment event carries the
# family's `event_prefix` in its log name, the convergence event does not.
EVENT_CONVERGENCE = "walk_forward_hmm_convergence_iters"
EVENT_SEGMENT_SKIPPED = "walk_forward_segment_skipped"


class RegimeEventRecord(NamedTuple):
    """One thing a walk-forward run did that an operator triages from: a segment's fit
    (`EVENT_CONVERGENCE`: iters_used, n_iter_cap, converged, seg_start, seg_end, train_end) or a
    segment that was not written (`EVENT_SEGMENT_SKIPPED`: seg_start, seg_end and the occupation
    gate's diagnostics, `reason` among them)."""

    kind: str
    fields: dict[str, Any]


class FamilyResult(NamedTuple):
    """Row-aligned walk-forward output for one family.

    `code` indexes the family's label tuple (NaN where unlabeled); `status` is the segment
    status per row; `numeric` is (7, n_rows) in the family's owned-column order; `events` are
    the per-segment fit and skip reports, in segment order.
    """

    code: np.ndarray
    status: np.ndarray
    numeric: np.ndarray
    events: tuple[RegimeEventRecord, ...] = ()


def _trend_observations(
    close: np.ndarray, volume: np.ndarray | None, params: HmmConfig, block_rows: int | None
) -> tuple[np.ndarray, int]:
    assert volume is not None  # the trend family declares volume as an input
    return _observations_trend(
        close,
        volume,
        params.hmm_vol_window,
        params.hmm_momentum_window,
        params.hmm_vol_of_vol_window,
        block_rows,
        params.hmm_momentum_vol_floor,
    )


def _volatility_observations(
    close: np.ndarray, volume: np.ndarray | None, params: HmmConfig, block_rows: int | None
) -> tuple[np.ndarray, int]:
    return _observations_volatility(
        close, params.hmm_volatility_vol_window, params.hmm_volatility_vol_of_vol_window, block_rows
    )


@dataclass(frozen=True, eq=False)
class RegimeFamilySpec:
    """Everything that differs between the two regime families, declared once: the vocabulary
    and label order, the log event prefix, where its model fields live in `HmmConfig`, how the
    three state-group probabilities map onto its numeric columns, its observation builder and
    input names, and the feature_vectors column and kernel-output names.

    `prob_order` indexes the (high-state mass, mid-state mass, low-state mass) triple that
    `_alpha_history_to_regime_probs` returns as (p_up, p_ranging, p_down): trend columns are
    (up, ranging, down) = (0, 1, 2) and volatility columns are (calm = the low group, elevated,
    turbulent = the high group) = (2, 1, 0).
    """

    family: str
    vocab: dict[str, str]
    labels: tuple[str, ...]
    event_prefix: str
    config_prefix: str
    prob_order: tuple[int, int, int]
    inputs: tuple[str, ...]
    build_observations: Callable[
        [np.ndarray, np.ndarray | None, HmmConfig, int | None], tuple[np.ndarray, int]
    ]
    regime_column: str
    code_output: str
    status_output: str
    numeric_outputs: tuple[str, ...]

    @property
    def owned_columns(self) -> tuple[str, ...]:
        """The feature_vectors columns this family writes, label first."""
        return (self.regime_column, *self.numeric_outputs)

    @property
    def needs_volume(self) -> bool:
        return "volume" in self.inputs

    def model_fields(self, params: HmmConfig) -> tuple[int, str]:
        """(n_components, covariance_type) of this family."""
        return (
            int(getattr(params, f"{self.config_prefix}_n_components")),
            str(getattr(params, f"{self.config_prefix}_covariance_type")),
        )

    def code_of_state(self, state_labels: tuple[str, ...]) -> np.ndarray:
        """Label-tuple index of each state's label (ValueError for a label outside the set)."""
        return np.array([self.labels.index(label) for label in state_labels], dtype=np.int64)


FAMILY_SPECS: dict[str, RegimeFamilySpec] = {
    FAMILY_TREND: RegimeFamilySpec(
        family=FAMILY_TREND,
        vocab=_TREND_VOCAB,
        labels=TREND_LABELS,
        event_prefix="",
        config_prefix="hmm",
        prob_order=(0, 1, 2),
        inputs=("close", "volume", "tf"),
        build_observations=_trend_observations,
        regime_column=REGIME_WRITER_OWNED_COLUMN_NAMES[0],
        code_output="_hmm_trend_code",
        status_output="_hmm_trend_segment_status",
        numeric_outputs=tuple(REGIME_WRITER_OWNED_COLUMN_NAMES[1:]),
    ),
    FAMILY_VOLATILITY: RegimeFamilySpec(
        family=FAMILY_VOLATILITY,
        vocab=_VOLATILITY_VOCAB,
        labels=VOLATILITY_LABELS,
        event_prefix="volatility_",
        config_prefix="hmm_volatility",
        prob_order=(2, 1, 0),
        inputs=("close", "tf"),
        build_observations=_volatility_observations,
        regime_column=REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[0],
        code_output="_hmm_volatility_code",
        status_output="_hmm_volatility_segment_status",
        numeric_outputs=tuple(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[1:]),
    ),
}
assert all(len(f.numeric_outputs) == N_NUMERIC_COLUMNS for f in FAMILY_SPECS.values())


def _run_durations(
    codes: np.ndarray, previous_code: int, carried_run: int
) -> tuple[np.ndarray, int]:
    """Bars the label has held at each row of one written segment, and the run length at its end.

    A run that continues the previous written segment's last label (`previous_code`, -1 for
    none) starts from `carried_run` instead of 0. Run-length arithmetic over the integer codes;
    the same counts as incrementing a duration per row.
    """
    index = np.arange(len(codes))
    starts_run = np.concatenate([[codes[0] != previous_code], codes[1:] != codes[:-1]])
    run_start = np.maximum.accumulate(np.where(starts_run, index, 0))
    durations = index - run_start + 1
    if not starts_run[0]:
        durations[run_start == 0] += carried_run
    return durations.astype(float), int(durations[-1])


def walk_forward_family_arrays(
    obs_matrix: np.ndarray,
    valid_offset: int,
    n_rows: int,
    params: HmmConfig,
    tf: str,
    spec: RegimeFamilySpec,
) -> FamilyResult:
    """Walk-forward decode of one family, as row-aligned arrays over the `n_rows` bar grid.

    `obs_matrix` row j belongs to bar row `valid_offset + j`. Rows outside a written segment
    are NaN in `code` and `numeric` and carry the segment status. The skip and reset rules are
    the writer's: a degenerate or non-converged segment is not written, and duration and the
    churn window restart at the first written bar after any skipped gap (churn is computed per
    written segment, so no label change is fabricated across a gap: Phase 172 code review WR-01).

    The numeric columns are in the family's owned-column order (`spec.numeric_outputs`).
    """
    n_components, covariance_type = spec.model_fields(params)
    refit_every_bars, initial_warmup_bars = params.walk_forward_schedule(tf)

    code = np.full(n_rows, np.nan)
    status = np.full(n_rows, STATUS_NO_MODEL)
    numeric = np.full((N_NUMERIC_COLUMNS, n_rows), np.nan)

    # One BLAS thread is part of the kernel's definition: with several threads the fit's low
    # bits differ from the golden and, on this box, run to run (test_regime_kernel.py). Every
    # BLAS call of the fit and the emission solves happens inside this call, so the caller's
    # `infra.blas_threads_per_worker` cannot change a regime label.
    with pinned_blas_threads():
        segment_results = _walk_forward_hmm_full(
            obs_matrix,
            n_components,
            covariance_type,
            params.hmm_n_iter,
            params.hmm_random_state,
            refit_every_bars,
            initial_warmup_bars,
            params.hmm_min_hold_bars,
            params.hmm_full_cov_min_obs,
            params.hmm_min_state_occupation,
            vocab=spec.vocab,
            min_obs_factor=params.hmm_min_obs_factor,
            covariance_ridge=params.hmm_covariance_ridge,
        )

    events: list[RegimeEventRecord] = []
    previous_code = -1
    carried_run = 0
    for seg in segment_results:
        rows = slice(valid_offset + seg["seg_start"], valid_offset + seg["seg_end"])
        events.append(
            RegimeEventRecord(
                EVENT_CONVERGENCE,
                {
                    "iters_used": seg["iters_used"],
                    "n_iter_cap": seg["n_iter_cap"],
                    "converged": seg["converged"],
                    "seg_start": seg["seg_start"],
                    "seg_end": seg["seg_end"],
                    "train_end": seg["seg_start"],
                },
            )
        )
        if seg["is_degenerate"]:
            events.append(
                RegimeEventRecord(
                    EVENT_SEGMENT_SKIPPED,
                    {"seg_start": seg["seg_start"], "seg_end": seg["seg_end"], **seg["gate_info"]},
                )
            )
            status[rows] = _GATE_REASON_STATUS.get(seg["gate_info"]["reason"], STATUS_OTHER_GATE)
            previous_code, carried_run = -1, 0  # continuity through a gap cannot be verified
            continue

        codes = spec.code_of_state(seg["state_labels"])[seg["states"]]
        durations, carried_run = _run_durations(codes, previous_code, carried_run)
        previous_code = int(codes[-1])
        masses = (seg["p_up"], seg["p_ranging"], seg["p_down"])
        status[rows] = STATUS_WRITTEN
        code[rows] = codes
        numeric[:, rows] = np.vstack(
            [
                *(masses[i] for i in spec.prob_order),
                seg["prob_val"],
                seg["entropy_val"],
                durations,
                _compute_hmm_churn(codes, params.hmm_churn_window),
            ]
        )

    return FamilyResult(code, status, numeric, tuple(events))
