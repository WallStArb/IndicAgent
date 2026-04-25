"""Tests for src.intelligence.swarm.graduation validation module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.intelligence.swarm.graduation import (
    EVAL_EXPIRY_DAYS,
    GATE_SPEARMAN_RHO,
    compute_expected_shortfall,
    compute_segment_power,
    compute_spearman,
    compute_value_add,
    compute_walk_forward,
    evaluate_all,
)


def _correlated_df(n: int = 100, rho: float = 0.8, seed: int = 42) -> pd.DataFrame:
    """Synthetic DataFrame with multiplier and pnl_r positively correlated."""
    rng = np.random.default_rng(seed)
    mult = rng.uniform(0, 1, n)
    noise = rng.normal(0, 0.5, n)
    pnl = rho * (mult - 0.5) * 4 + noise  # roughly correlated with mult
    ts = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame({"multiplier": mult, "pnl_r": pnl, "ts": ts})


def _anticorrelated_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Synthetic DataFrame with multiplier and pnl_r negatively correlated."""
    rng = np.random.default_rng(seed)
    mult = rng.uniform(0, 1, n)
    noise = rng.normal(0, 0.2, n)
    pnl = -2.0 * mult + noise  # negatively correlated
    ts = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame({"multiplier": mult, "pnl_r": pnl, "ts": ts})


# --- Gate constant tests ---

def test_gate_constants_positive():
    """GATE_SPEARMAN_RHO must be +0.15 (positive multiplier semantics)."""
    assert GATE_SPEARMAN_RHO == 0.15


# --- compute_spearman tests ---

def test_compute_spearman_passes_when_correlated():
    """Strong positive correlation should pass the Spearman gate."""
    df = _correlated_df(n=100, rho=0.8)
    result = compute_spearman(df)
    assert result["rho"] > 0.15
    assert result["pass"] is True


def test_compute_spearman_fails_when_anticorrelated():
    """Negative correlation must fail the Spearman gate."""
    df = _anticorrelated_df(n=100)
    result = compute_spearman(df)
    assert result["rho"] < 0.0
    assert result["pass"] is False


def test_compute_spearman_insufficient_n():
    """Fewer than 10 rows must return pass=False."""
    df = _correlated_df(n=5)
    result = compute_spearman(df)
    assert result["pass"] is False


# --- compute_expected_shortfall tests ---

def test_compute_expected_shortfall_pass():
    """Bottom decile of multiplier with avg pnl_r = -1.0 must pass cvar gate."""
    # Build df where lowest-multiplier rows have pnl_r = -1.0
    rng = np.random.default_rng(42)
    n = 100
    # Bottom 10% multiplier (index 0..9): pnl_r = -1.0 exactly
    # Rest: pnl_r = +0.5
    mult = np.linspace(0, 1, n)  # sorted 0→1
    pnl = np.where(mult < np.percentile(mult, 10), -1.0, 0.5)
    ts = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    df = pd.DataFrame({"multiplier": mult, "pnl_r": pnl, "ts": ts})
    result = compute_expected_shortfall(df)
    # Bottom decile avg pnl_r = -1.0 <= -0.5 → pass
    assert result["cvar"] <= -0.5
    assert result["pass"] is True


# --- compute_segment_power tests ---

def test_compute_segment_power_returns_finite_for_large_n():
    """n=100 should return a finite MDE < 0.5."""
    mde = compute_segment_power(100)
    assert mde < 0.5
    assert mde != float("inf")


def test_compute_segment_power_inf_for_small_n():
    """n=5 is too small — MDE must be inf."""
    mde = compute_segment_power(5)
    assert mde == float("inf")


# --- compute_walk_forward tests ---

def test_compute_walk_forward_split():
    """100-row df with 70% train fraction → train_n=70, val_n=30."""
    df = _correlated_df(n=100, rho=0.8)
    result = compute_walk_forward(df, train_fraction=0.7)
    assert result["train_n"] == 70
    assert result["val_n"] == 30


# --- compute_value_add tests ---

def test_compute_value_add_positive():
    """Filtered (high-multiplier) trades with better Sharpe → pass=True."""
    rng = np.random.default_rng(42)
    n = 200
    # Low-multiplier rows (< 0.5): poor pnl_r (mean -0.3)
    # High-multiplier rows (>= 0.5): good pnl_r (mean +0.5)
    mult = rng.uniform(0, 1, n)
    pnl = np.where(mult >= 0.5, rng.normal(0.5, 0.3, n), rng.normal(-0.3, 0.3, n))
    ts = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(n)]
    df = pd.DataFrame({"multiplier": mult, "pnl_r": pnl, "ts": ts})
    result = compute_value_add(df)
    assert result["pass"] is True
    assert result["delta"] > 0


# --- evaluate_all tests ---

def test_evaluate_all_returns_payload_schema():
    """evaluate_all must return all 15 required keys with correct types."""
    df = _correlated_df(n=200, rho=0.8)
    result = evaluate_all(df, transform_id="test_xform", segment_key="trend.5m")
    required_keys = {
        "transform_id",
        "transform_version",
        "segment_key",
        "n",
        "spearman_rho",
        "spearman_p",
        "calibration_max_error",
        "cvar_bottom_decile",
        "mde",
        "val_rho",
        "overfitting_risk",
        "sharpe_delta",
        "is_graduated",
        "evaluated_at",
        "expires_at",
    }
    assert required_keys.issubset(result.keys()), (
        f"Missing keys: {required_keys - set(result.keys())}"
    )
    assert result["transform_id"] == "test_xform"
    assert result["segment_key"] == "trend.5m"
    assert result["transform_version"] == "v1"
    assert isinstance(result["n"], int)
    assert isinstance(result["is_graduated"], bool)
    assert isinstance(result["overfitting_risk"], bool)
    assert result["evaluated_at"].endswith("Z")
    assert result["expires_at"].endswith("Z")
    # expires_at - evaluated_at == 90 days
    evaluated_at = datetime.fromisoformat(result["evaluated_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
    assert (expires_at - evaluated_at).days == 90


def test_evaluate_all_is_graduated_requires_all_gates():
    """A DataFrame where one gate fails must yield is_graduated=False."""
    # Strongly anticorrelated → Spearman gate fails → is_graduated must be False
    df = _anticorrelated_df(n=200)
    result = evaluate_all(df, transform_id="failing_xform")
    assert result["is_graduated"] is False
