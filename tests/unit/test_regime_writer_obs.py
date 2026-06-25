"""Unit tests for the 5D HMM observation builder in regime_writer.

Tests verify shape, content, and valid-row count for the enriched observation matrix.
No DB, no GaussianHMM. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.regime_writer import _build_obs_matrix


def _make_prices(n: int, seed: int = 42) -> tuple[list, list[float], list[float]]:
    """Synthetic price + volume series of length n."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0001, 0.001, n)
    closes = [100.0 * np.exp(np.sum(returns[:i])) for i in range(n)]
    volumes = [1_000_000 * (1 + rng.uniform(-0.3, 0.3)) for _ in range(n)]
    ts = list(range(n))
    return ts, closes, volumes


def test_obs_matrix_shape_5d():
    """Output matrix must have 5 columns."""
    ts, closes, volumes = _make_prices(500)
    obs, valid_ts = _build_obs_matrix(
        ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )
    assert obs.shape[1] == 5, f"Expected 5 columns, got {obs.shape[1]}"


def test_obs_matrix_valid_rows_discarded():
    """First max(vol_window, momentum_window, vol_of_vol_window) rows must be discarded."""
    ts, closes, volumes = _make_prices(500)
    vol_window = 20
    obs, valid_ts = _build_obs_matrix(
        ts, closes, volumes, vol_window=vol_window, momentum_window=20, vol_of_vol_window=20
    )
    # n returns = 499, valid_start = 19, so valid rows = 499 - 19 = 480
    expected_rows = (len(closes) - 1) - (vol_window - 1)
    assert obs.shape[0] == expected_rows, f"Expected {expected_rows} rows, got {obs.shape[0]}"
    assert len(valid_ts) == obs.shape[0]


def test_obs_matrix_no_nan_or_inf():
    """No NaN or Inf values in the observation matrix."""
    ts, closes, volumes = _make_prices(500)
    obs, _ = _build_obs_matrix(
        ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )
    assert not np.any(np.isnan(obs)), "NaN found in observation matrix"
    assert not np.any(np.isinf(obs)), "Inf found in observation matrix"


def test_obs_matrix_momentum_non_trivial():
    """Momentum column (index 2) must not be all zeros (would indicate a bug)."""
    ts, closes, volumes = _make_prices(500)
    obs, _ = _build_obs_matrix(
        ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )
    assert np.std(obs[:, 2]) > 0, "Momentum column is constant — likely a bug"


def test_obs_matrix_rel_volume_non_trivial():
    """Relative volume column (index 4) must not be all zeros."""
    ts, closes, volumes = _make_prices(500)
    obs, _ = _build_obs_matrix(
        ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )
    assert np.std(obs[:, 4]) > 0, "Relative volume column is constant — likely a bug"


def test_obs_matrix_empty_on_insufficient_data():
    """Too-short series must return empty obs matrix."""
    ts, closes, volumes = _make_prices(30)  # less than vol_window=20 + warmup
    obs, valid_ts = _build_obs_matrix(
        ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )
    # 30 - 1 = 29 returns, valid_start = 19, rows = 10 > 0 but marginal
    # Use a series shorter than valid_start:
    ts2, closes2, volumes2 = _make_prices(10)
    obs2, valid_ts2 = _build_obs_matrix(
        ts2, closes2, volumes2, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )
    assert obs2.shape[0] == 0
    assert len(valid_ts2) == 0


def test_obs_matrix_different_windows():
    """Larger momentum window means more rows discarded."""
    ts, closes, volumes = _make_prices(500)
    obs20, _ = _build_obs_matrix(
        ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20
    )
    obs40, _ = _build_obs_matrix(
        ts, closes, volumes, vol_window=20, momentum_window=40, vol_of_vol_window=20
    )
    assert obs40.shape[0] < obs20.shape[0]
