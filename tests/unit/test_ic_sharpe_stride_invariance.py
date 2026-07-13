"""Unit tests: todo 096 fix — _compute_ic_rolling_metrics window sizing must be
stride-invariant.

Before the fix, `sharpe_window_size` (raw bars) was floor-divided by `stride` inside
the function, so the SAME subsampled series length produced a different window count
(and therefore a different ic_sharpe) purely as a function of which lookahead scale's
stride was passed in — not because of any real difference in the underlying signal.
See .planning/todos/pending/096-frame-hold-horizon-vs-feature-lookahead-mismatch.md
and scripts/analysis/ic_sharpe_stride_bias_check.py for the full Monte Carlo proof.

The fix: window size is a fixed target expressed directly in SUBSAMPLED bars
(`sharpe_window_size_subsampled`), not derived from a raw-bar constant divided by
stride. This test asserts the mechanical, deterministic consequence: for a fixed
number of subsampled observations, n_windows must be identical regardless of stride.

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import _compute_ic_rolling_metrics


@dataclass(frozen=True)
class _StubConfig:
    """Minimal SharpeWindowConfig-satisfying test double — ic_math.py is a pure
    module with no dependency on the concrete ICEngineConfig/EnsembleICConfig
    dataclasses, so tests shouldn't need to construct either."""

    sharpe_window_size_subsampled: int
    sharpe_min_windows: int
    hac_max_lag: int


def test_n_windows_independent_of_stride():
    """Same subsampled observation count -> same n_windows, at any stride.

    n=1000 subsampled bars, sharpe_window_size_subsampled=100 -> 10 windows,
    regardless of whether this data came from a stride=1 or stride=60 subsample.
    """
    rng = np.random.default_rng(42)
    n_obs = 1000
    n_features = 3
    X_sub = rng.standard_normal((n_obs, n_features))
    returns_sub = rng.standard_normal((n_obs, 1))
    complete_mask = np.ones(n_obs, dtype=bool)
    non_degenerate_mask = np.ones(n_features, dtype=bool)
    config = _StubConfig(
        sharpe_window_size_subsampled=100,
        sharpe_min_windows=3,
        hac_max_lag=3,
    )

    _, _, _, _, n_windows_fast = _compute_ic_rolling_metrics(
        X_sub, returns_sub, 0, complete_mask, config, non_degenerate_mask, n_features, 1
    )
    _, _, _, _, n_windows_extended = _compute_ic_rolling_metrics(
        X_sub, returns_sub, 0, complete_mask, config, non_degenerate_mask, n_features, 60
    )

    assert n_windows_fast == 10, f"Expected 10 windows at stride=1, got {n_windows_fast}"
    assert n_windows_extended == 10, f"Expected 10 windows at stride=60, got {n_windows_extended}"
    assert n_windows_fast == n_windows_extended, (
        f"n_windows must not depend on stride: stride=1 gave {n_windows_fast}, "
        f"stride=60 gave {n_windows_extended}"
    )


def test_ic_sharpe_stride_invariant_for_fixed_true_signal():
    """Monte Carlo sanity check: mean ic_sharpe for a FIXED true rank correlation
    must be approximately equal across strides once window sizing is stride-invariant.

    Uses a Gaussian copula (same construction as ic_sharpe_stride_bias_check.py) to
    generate synthetic (X, Y) with a known, non-decaying Spearman rho, subsampled at
    two different strides. Before the fix this ratio was ~3.4-3.6x (see the Monte
    Carlo proof in todo 096); after the fix it should be close to 1.0.
    """

    rng = np.random.default_rng(7)
    true_rho = 0.06
    pearson_rho = 2 * np.sin(true_rho * np.pi / 6)
    # n_raw must clear the sharpe_min_windows=30 gate at the SLOWEST stride tested
    # (60): 200_000 // 60 = 3333 subsampled bars // 100-bar window = 33 windows.
    n_raw = 200_000
    n_reps = 40
    config = _StubConfig(
        sharpe_window_size_subsampled=100,
        sharpe_min_windows=30,
        hac_max_lag=3,
    )

    def sharpe_at_stride(stride: int) -> list[float]:
        vals = []
        for _ in range(n_reps):
            xy = rng.multivariate_normal([0, 0], [[1, pearson_rho], [pearson_rho, 1]], size=n_raw)
            x_raw, y_raw = xy[:, 0], xy[:, 1]
            sub_idx = np.arange(0, n_raw, stride)
            x_sub = x_raw[sub_idx].reshape(-1, 1)
            y_sub = y_raw[sub_idx].reshape(-1, 1)
            complete_mask = np.ones(len(sub_idx), dtype=bool)
            non_degenerate_mask = np.array([True])
            sharpe_arr, _, _, _, _ = _compute_ic_rolling_metrics(
                x_sub, y_sub, 0, complete_mask, config, non_degenerate_mask, 1, stride
            )
            if not np.isnan(sharpe_arr[0]):
                vals.append(float(sharpe_arr[0]))
        return vals

    fast_vals = sharpe_at_stride(5)
    extended_vals = sharpe_at_stride(60)

    assert len(fast_vals) > 10 and len(extended_vals) > 10, "gate should pass at both strides"
    fast_mean = np.mean(fast_vals)
    extended_mean = np.mean(extended_vals)
    ratio = fast_mean / extended_mean

    assert 0.7 < ratio < 1.4, (
        f"fast/extended ic_sharpe ratio should be near 1.0 (stride-invariant), got {ratio:.2f} "
        f"(fast_mean={fast_mean:.3f}, extended_mean={extended_mean:.3f})"
    )
