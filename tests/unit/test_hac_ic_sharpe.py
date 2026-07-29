"""Unit tests: Newey-West HAC IC Sharpe correctness.

Tests verify that _hac_sharpe_nd() from src.intelligence.statistics.ic_math:
  1. Returns naive Sharpe when max_lag=0 (HAC disabled)
  2. Returns naive Sharpe when IC series has zero autocorrelation (inflation=1)
  3. Returns Sharpe <= naive Sharpe for positively autocorrelated IC series
  4. Floors inflation at 1 (never more precise than i.i.d.)
  5. Handles n < max_lag + 2 gracefully (falls back to naive Sharpe)
  6. Output shape matches number of features
  7. Integration: _compute_ic_rolling_metrics returns 5-tuple

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import ICEngineConfig
from src.intelligence.statistics.ic_math import _compute_ic_rolling_metrics, _hac_sharpe_nd

# ---------------------------------------------------------------------------
# _hac_sharpe_nd tests
# ---------------------------------------------------------------------------


def test_hac_disabled_equals_naive():
    """max_lag=0 must produce the same result as naive Sharpe."""
    rng = np.random.default_rng(42)
    window_ics = rng.normal(0.05, 0.03, size=(50, 4))

    hac = _hac_sharpe_nd(window_ics, max_lag=0)
    mean_ic = window_ics.mean(axis=0)
    std_ic = np.sqrt(((window_ics - mean_ic) ** 2).mean(axis=0))
    naive = np.where(std_ic > 1e-10, mean_ic / std_ic, 0.0)

    np.testing.assert_allclose(hac, naive, atol=1e-12)


def test_iid_series_hac_equals_naive():
    """i.i.d. IC series must have HAC Sharpe ≈ naive Sharpe (zero autocorrelation)."""
    rng = np.random.default_rng(0)
    # Large i.i.d. window count so autocorrelations wash out
    window_ics = rng.normal(0.06, 0.02, size=(200, 3))

    hac = _hac_sharpe_nd(window_ics, max_lag=3)
    mean_ic = window_ics.mean(axis=0)
    std_ic = np.sqrt(((window_ics - mean_ic) ** 2).mean(axis=0))
    naive = np.where(std_ic > 1e-10, mean_ic / std_ic, 0.0)

    # At n=200 with i.i.d. data, lag autocorrelations are ~O(1/sqrt(n)) ≈ 0.07
    # HAC and naive should agree within 20%
    np.testing.assert_allclose(hac, naive, rtol=0.20)


def test_autocorrelated_series_hac_less_than_naive():
    """Positively autocorrelated IC series must have HAC Sharpe < naive Sharpe."""
    rng = np.random.default_rng(7)
    n = 80
    # AR(1) with strong persistence (phi=0.8) — regime-persistent feature
    ic = np.zeros(n)
    ic[0] = rng.normal(0.05, 0.01)
    for t in range(1, n):
        ic[t] = 0.8 * ic[t - 1] + rng.normal(0.01, 0.005)

    window_ics = ic.reshape(-1, 1)  # [n, 1]
    hac = _hac_sharpe_nd(window_ics, max_lag=3)
    mean_ic = window_ics.mean(axis=0)
    std_ic = np.sqrt(((window_ics - mean_ic) ** 2).mean(axis=0))
    naive = np.where(std_ic > 1e-10, mean_ic / std_ic, 0.0)

    assert np.all(
        hac <= naive + 1e-10
    ), f"HAC Sharpe {hac} should be <= naive Sharpe {naive} for AR(1) IC series"
    # With phi=0.8 the inflation factor at K=3 is substantial — HAC should be noticeably lower
    assert np.all(
        hac < naive * 0.95
    ), f"HAC Sharpe {hac} should be materially lower than naive {naive} for AR(1) phi=0.8"


def test_inflation_floored_at_one():
    """Negatively autocorrelated IC must not produce HAC Sharpe > naive (inflation >= 1)."""
    rng = np.random.default_rng(13)
    n = 60
    # Alternating IC — strong negative autocorrelation, inflation formula could go < 1
    ic = np.array([0.05 if i % 2 == 0 else 0.03 for i in range(n)], dtype=float)
    window_ics = ic.reshape(-1, 1)

    hac = _hac_sharpe_nd(window_ics, max_lag=3)
    mean_ic = window_ics.mean(axis=0)
    std_ic = np.sqrt(((window_ics - mean_ic) ** 2).mean(axis=0))
    naive = np.where(std_ic > 1e-10, mean_ic / std_ic, 0.0)

    # Inflation is floored at 1, so HAC Sharpe must not exceed naive Sharpe
    assert np.all(
        hac <= naive + 1e-10
    ), f"HAC Sharpe {hac} must not exceed naive {naive} (inflation floor=1)"


def test_small_n_falls_back_to_naive():
    """When n < max_lag + 2, must fall back to naive Sharpe without error."""
    window_ics = np.array([[0.05, 0.03], [0.04, 0.06], [0.06, 0.02]])  # n=3, max_lag=3
    hac = _hac_sharpe_nd(window_ics, max_lag=3)
    mean_ic = window_ics.mean(axis=0)
    std_ic = np.sqrt(((window_ics - mean_ic) ** 2).mean(axis=0))
    naive = np.where(std_ic > 1e-10, mean_ic / std_ic, 0.0)

    np.testing.assert_allclose(hac, naive, atol=1e-12)


def test_hac_output_shape_matches_feature_count():
    """Output must match number of input features."""
    rng = np.random.default_rng(99)
    for p in [1, 5, 61]:
        window_ics = rng.normal(0.04, 0.02, size=(40, p))
        hac = _hac_sharpe_nd(window_ics, max_lag=3)
        assert hac.shape == (p,), f"Shape mismatch: expected ({p},), got {hac.shape}"


# ---------------------------------------------------------------------------
# Integration: _compute_ic_rolling_metrics returns 5-tuple
# ---------------------------------------------------------------------------


def test_rolling_metrics_returns_five_tuple():
    """_compute_ic_rolling_metrics must return (sharpe, sharpe_hac, sortino, win_rate, n_windows)."""
    rng = np.random.default_rng(5)
    n_obs = 300
    n_features = 4
    X_sub = rng.standard_normal((n_obs, n_features))
    returns_sub = rng.standard_normal((n_obs, 4))  # 4 scales
    non_degenerate_mask = np.ones(n_features, dtype=bool)
    config = ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=50,
        sharpe_window_size_subsampled=50,
        sharpe_min_windows=3,
        subsample_min_stride=5,
        min_reliable_n=100,
        cluster_max_corr=0.70,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
    )

    result = _compute_ic_rolling_metrics(
        X_sub,
        returns_sub,
        0,
        np.ones(n_obs, dtype=bool),
        config,
        non_degenerate_mask,
        n_features,
        1,
    )
    assert len(result) == 5, f"Expected 5-tuple, got {len(result)}-tuple"
    sharpe_arr, sharpe_hac_arr, sortino_arr, win_rate_arr, n_windows = result
    assert sharpe_arr.shape == (n_features,)
    assert sharpe_hac_arr.shape == (n_features,)
    assert n_windows >= 3


# ---------------------------------------------------------------------------
# Todo 146: per-tf lookahead grid
# ---------------------------------------------------------------------------


def test_lookaheads_for_returns_per_tf_values():
    """lookaheads_for(tf) must resolve each scale from that tf's own dict entry,
    not a single global scalar -- the whole point of todo 146's per-tf grid fix."""
    config = ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=50,
        sharpe_window_size_subsampled=50,
        sharpe_min_windows=3,
        subsample_min_stride=5,
        min_reliable_n=100,
        cluster_max_corr=0.70,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
    )
    assert config.lookaheads_for("5m") == {"fast": 1, "mid": 6, "slow": 12, "extended": 39}
    assert config.lookaheads_for("15m") == {"fast": 1, "mid": 2, "slow": 5, "extended": 10}
    assert config.lookaheads_for("1d") == {"fast": 1, "mid": 2, "slow": 5, "extended": 10}
