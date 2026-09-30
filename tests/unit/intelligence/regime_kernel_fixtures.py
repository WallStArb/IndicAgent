"""Shared inputs for the regime kernel tests and the golden capture script (186-13).

Not a test module. `make_synthetic_regime_bars` is a regime-switching price and volume
generator; `SMALL_HMM_APR` is the stated small configuration the synthetic golden and the
probe tests run under, as APR key -> value so the unchanged writer functions, the kernel and the
capture script all read the same numbers.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

# Label index order stored in the golden (index -1 means unwritten). The kernels' own label
# tuples must equal these; test_regime_kernel.py asserts it.
TREND_LABELS: tuple[str, ...] = (
    "trending_up",
    "trending_down",
    "ranging",
    "transition_up",
    "transition_down",
)
VOLATILITY_LABELS: tuple[str, ...] = ("calm", "elevated", "turbulent")
FAMILY_LABELS: dict[str, tuple[str, ...]] = {
    "trend": TREND_LABELS,
    "volatility": VOLATILITY_LABELS,
}

# Numeric column order of the golden, per family, equal to
# REGIME_WRITER_OWNED_COLUMN_NAMES[1:] and REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[1:].
N_NUMERIC_COLUMNS = 7

# Stated small configuration (186-13): trend n_components 3, windows 20, n_iter 50; volatility
# n_components 3, vol_window 20, vol_of_vol_window 60; the remaining values are the writer's own
# fallbacks. The per-tf schedule is small so a 3,000-bar series has several refit segments.
SMALL_HMM_APR: dict[str, Any] = {
    "feature.hmm.n_components": 3,
    "feature.hmm.vol_window": 20,
    "feature.hmm.n_iter": 50,
    "alpha.hmm.random_state": 42,
    "feature.hmm.obs_momentum_window": 20,
    "feature.hmm.obs_vol_of_vol_window": 20,
    "feature.hmm.covariance_type": "full",
    "feature.hmm.min_hold_bars": 3,
    "feature.hmm.full_cov_min_obs": 500,
    "feature.hmm.min_state_occupation": 0.05,
    "feature.hmm.churn_window": 10,
    "feature.hmm.min_obs_factor": 50,
    "alpha.hmm_volatility.n_components": 3,
    "alpha.hmm_volatility.vol_window": 20,
    "alpha.hmm_volatility.vol_of_vol_window": 60,
    "alpha.hmm_volatility.covariance_type": "full",
    "alpha.hmm.walk_forward.refit_every_bars.5m": 900,
    "alpha.hmm.walk_forward.initial_warmup_bars.5m": 1500,
    "alpha.hmm.walk_forward.refit_every_bars.15m": 600,
    "alpha.hmm.walk_forward.initial_warmup_bars.15m": 1200,
    "alpha.hmm.walk_forward.refit_every_bars.1h": 450,
    "alpha.hmm.walk_forward.initial_warmup_bars.1h": 900,
    "alpha.hmm.walk_forward.refit_every_bars.1d": 300,
    "alpha.hmm.walk_forward.initial_warmup_bars.1d": 600,
}


def make_synthetic_regime_bars(n: int, seed: int) -> dict[str, np.ndarray]:
    """Close and volume of a series that switches between calm-up, turbulent-down and quiet
    drift-free regimes in blocks of a few hundred bars, with volume tied to the volatility."""
    rng = np.random.default_rng(seed)
    params = ((0.0008, 0.004), (-0.0010, 0.018), (0.0, 0.009))
    returns = np.empty(n)
    vol_level = np.empty(n)
    i = 0
    while i < n:
        block = int(rng.integers(150, 400))
        drift, vol = params[int(rng.integers(0, len(params)))]
        stop = min(n, i + block)
        returns[i:stop] = rng.normal(drift, vol, stop - i)
        vol_level[i:stop] = vol
        i = stop
    close = 100.0 * np.exp(np.cumsum(returns))
    volume = np.exp(rng.normal(13.0 + 20.0 * vol_level, 0.3, n))
    base = datetime(2010, 1, 4, 21, 0, tzinfo=UTC)
    ts = np.array(
        [int((base + timedelta(days=int(d))).timestamp()) * 1_000_000_000 for d in range(n)],
        dtype=np.int64,
    )
    return {"ts": ts, "close": close, "volume": volume}


def _canonical_f32(values: np.ndarray) -> np.ndarray:
    """float32 with one NaN bit pattern and no negative zero, for byte digests."""
    arr = np.asarray(values, dtype=np.float32)
    arr = np.where(np.isnan(arr), np.float32("nan"), arr)
    return (arr + np.float32(0.0)).astype(np.float32)


def digest_case(labels: np.ndarray, columns: np.ndarray) -> dict[str, Any]:
    """sha256 of the int8 label indices and of each canonicalized float32 numeric column."""
    label_bytes = np.asarray(labels, dtype=np.int8).tobytes()
    return {
        "rows_written": int((np.asarray(labels) >= 0).sum()),
        "labels_sha256": hashlib.sha256(label_bytes).hexdigest(),
        "columns_sha256": [
            hashlib.sha256(_canonical_f32(col).tobytes()).hexdigest() for col in columns
        ],
    }


REGIME_SKIP_REASON = "HMM fit cost and per-tf schedule; covered by test_regime_kernel.py"


def non_regime_kernels(registry) -> tuple:
    """The registry's kernels without the regime origin (which needs the `tf` external and a
    real-length series; test_regime_kernel.py covers it)."""
    return tuple(k for k in registry.kernels if k.origin != "regime")


def non_regime_outputs(registry) -> list[str]:
    return [o for k in non_regime_kernels(registry) for o in k.outputs]


def registry_without_regime(registry):
    """A registry over the non-regime kernels, for probe_registry runs."""
    from src.intelligence.features.contract.registry import KernelRegistry

    return KernelRegistry.from_kernels(
        non_regime_kernels(registry),
        [e for e in registry.external_inputs if e.name != "tf"],
    )
