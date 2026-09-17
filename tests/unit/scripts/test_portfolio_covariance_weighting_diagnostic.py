"""Tests for scripts/analysis/portfolio_covariance_weighting_diagnostic.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.portfolio_covariance_weighting_diagnostic import (
    compute_mu,
    instrument_covariance,
    log_returns,
    shrink_instrument_ic,
    standardize_scores,
)


def test_standardize_scores_zero_mean_unit_variance():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = standardize_scores(s)
    assert z.mean() == pytest.approx(0.0, abs=1e-10)
    assert z.std(ddof=0) == pytest.approx(1.0, abs=1e-10)


def test_standardize_scores_constant_series_returns_zero_not_nan():
    # A degenerate all-equal score series has zero variance -- must not divide by zero.
    s = pd.Series([2.0, 2.0, 2.0])
    z = standardize_scores(s)
    assert (z == 0.0).all()


def test_standardize_scores_removes_cross_instrument_scale_mismatch():
    # Instrument A's raw score has std 0.2, instrument B's has std 2.0 -- same underlying
    # signal shape, different scale. After standardization both must have unit variance,
    # eliminating the scale artifact the spec review flagged.
    a = pd.Series(np.array([-0.2, 0.0, 0.2]))
    b = pd.Series(np.array([-2.0, 0.0, 2.0]))
    za, zb = standardize_scores(a), standardize_scores(b)
    np.testing.assert_allclose(za.to_numpy(), zb.to_numpy())


def test_shrink_instrument_ic_shrinks_toward_leave_one_out_peer_mean():
    # Three instruments, ic_raw = [0.10, 0.20, 0.30], all n_eff=100 (default k=100 -> w=0.5).
    ic_raw = np.array([0.10, 0.20, 0.30])
    n_eff = np.array([100.0, 100.0, 100.0])
    shrunk = shrink_instrument_ic(ic_raw, n_eff, k=100.0)
    # Instrument 0's leave-one-out peer mean is (0.20+0.30)/2=0.25; w=100/(100+100)=0.5
    # shrunk[0] = 0.5*0.10 + 0.5*0.25 = 0.175
    assert shrunk[0] == pytest.approx(0.175, abs=1e-9)


def test_shrink_instrument_ic_zero_n_eff_falls_fully_to_prior():
    ic_raw = np.array([0.50, 0.10, 0.10])
    n_eff = np.array([0.0, 100.0, 100.0])
    shrunk = shrink_instrument_ic(ic_raw, n_eff, k=100.0)
    # n_eff=0 -> full shrinkage to leave-one-out prior = mean(0.10, 0.10) = 0.10, ignoring 0.50.
    assert shrunk[0] == pytest.approx(0.10, abs=1e-9)


def test_compute_mu_matches_hand_computed_formula():
    ic_shrunk = np.array([0.05, -0.02])
    sigma = np.array([0.01, 0.02])
    z_latest = np.array([1.5, -0.5])
    mu = compute_mu(ic_shrunk, sigma, z_latest)
    expected = np.array([0.05 * 0.01 * 1.5, -0.02 * 0.02 * -0.5])
    np.testing.assert_allclose(mu, expected)


def test_log_returns_matches_hand_computed_values():
    close = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=pd.date_range("2026-01-01", periods=3))
    r = log_returns(close)
    assert r.shape == (2, 1)  # first row has no prior bar
    np.testing.assert_allclose(r["A"].to_numpy(), [np.log(1.10), np.log(1.10)], atol=1e-9)


def test_instrument_covariance_shape_and_symbol_order():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2026-01-01", periods=60)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(60, 3)), index=idx, columns=["A", "B", "C"])
    cov, corr, symbols = instrument_covariance(returns)
    assert cov.shape == (3, 3)
    assert corr.shape == (3, 3)
    assert symbols == ["A", "B", "C"]
    np.testing.assert_allclose(np.diag(corr), 1.0, atol=1e-9)


def test_instrument_covariance_drops_sparse_symbol():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-01", periods=60)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(60, 2)), index=idx, columns=["A", "B"])
    returns["C"] = np.nan
    returns.loc[returns.index[:5], "C"] = 0.001  # only 5 obs, below _CORR_MIN_PERIODS=20
    cov, corr, symbols = instrument_covariance(returns)
    assert symbols == ["A", "B"]
    assert cov.shape == (2, 2)
