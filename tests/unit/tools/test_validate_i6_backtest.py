"""Unit tests for validate_i6_backtest.py tool."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from tools.validate_i6_backtest import validate_backtest_results


@pytest.fixture
def perfect_correlation_data():
    """Create synthetic data with perfect positive correlation (IC=1.0)."""
    return pd.DataFrame(
        {
            "ts": [datetime(2026, 1, 1, i // 60, i % 60, tzinfo=UTC) for i in range(100)],
            "symbol": ["ES"] * 100,
            "tf": ["5m"] * 100,
            "test_score": [i / 100.0 for i in range(100)],  # 0.0 to 0.99
            "pnl_r": [i / 100.0 for i in range(100)],  # Same values = perfect correlation
            "hmm_regime": [0 if i < 33 else 1 if i < 66 else 2 for i in range(100)],
        }
    )


@pytest.fixture
def no_correlation_data():
    """Create synthetic data with no correlation (IC≈0.0)."""
    import random

    random.seed(42)
    return pd.DataFrame(
        {
            "ts": [datetime(2026, 1, 1, i // 60, i % 60, tzinfo=UTC) for i in range(100)],
            "symbol": ["ES"] * 100,
            "tf": ["5m"] * 100,
            "test_score": [random.random() for _ in range(100)],
            "pnl_r": [random.random() for _ in range(100)],
            "hmm_regime": [0 if i < 33 else 1 if i < 66 else 2 for i in range(100)],
        }
    )


@pytest.fixture
def regime_segmented_data():
    """Create data where correlation differs by regime."""
    import random

    random.seed(42)
    return pd.DataFrame(
        {
            "ts": [datetime(2026, 1, 1, i // 60, i % 60, tzinfo=UTC) for i in range(90)],
            "symbol": ["ES"] * 90,
            "tf": ["5m"] * 90,
            # Regime 0: positive correlation
            # Regime 1: negative correlation
            # Regime 2: weak/no correlation
            "test_score": [
                i / 30.0 if i < 30 else -(i - 30) / 30.0 if i < 60 else random.random() for i in range(90)
            ],
            "pnl_r": [
                i / 30.0 if i < 30 else (i - 30) / 30.0 if i < 60 else random.random() for i in range(90)
            ],
            "hmm_regime": [0 if i < 30 else 1 if i < 60 else 2 for i in range(90)],
        }
    )


def test_validate_perfect_correlation(perfect_correlation_data):
    """Test validation with synthetic data having IC=1.0."""
    result = validate_backtest_results(
        perfect_correlation_data,
        field_name="test_score",
        min_ic=0.05,
        alpha=0.01,
        min_n=30,
    )

    # Verify overall result
    assert result.field_name == "test_score"
    assert result.n == 100
    assert result.ic > 0.99  # Nearly perfect correlation
    assert result.p_value < 0.001  # Highly significant
    assert result.passed is True

    # Verify regime results
    assert len(result.regime_results) == 3  # 3 regimes
    assert "hmm_regime_0" in result.regime_results
    assert "hmm_regime_1" in result.regime_results
    assert "hmm_regime_2" in result.regime_results


def test_validate_no_correlation(no_correlation_data):
    """Test validation with synthetic data having IC≈0.0."""
    result = validate_backtest_results(
        no_correlation_data,
        field_name="test_score",
        min_ic=0.05,
        alpha=0.01,
        min_n=30,
    )

    # Verify overall result
    assert result.field_name == "test_score"
    assert result.n == 100
    assert abs(result.ic) < 0.2  # Low correlation
    assert result.p_value > 0.05  # Not significant
    assert result.passed is False


def test_validate_regime_segmentation(regime_segmented_data):
    """Test that regime-segmented validation produces 3 separate results."""
    result = validate_backtest_results(
        regime_segmented_data,
        field_name="test_score",
        min_ic=0.05,
        alpha=0.01,
        min_n=30,
    )

    # Verify regime results exist
    assert len(result.regime_results) == 3

    # Regime 0: positive correlation (should pass)
    regime_0 = result.regime_results["hmm_regime_0"]
    assert regime_0.n == 30
    assert regime_0.ic > 0.8  # Strong positive correlation
    assert regime_0.passed is True

    # Regime 1: negative correlation (should fail - IC is negative)
    regime_1 = result.regime_results["hmm_regime_1"]
    assert regime_1.n == 30
    assert regime_1.ic < -0.8  # Strong negative correlation
    assert regime_1.passed is False  # Negative IC < min_ic

    # Regime 2: weak/no correlation (should fail)
    regime_2 = result.regime_results["hmm_regime_2"]
    assert regime_2.n == 30
    assert abs(regime_2.ic) < 0.5  # Weak correlation
    assert regime_2.passed is False


def test_validate_bonferroni_correction():
    """Test that Bonferroni correction is applied via alpha parameter."""
    # Create data with moderate correlation (IC=0.15)
    data = pd.DataFrame(
        {
            "ts": [datetime(2026, 1, 1, i // 60, i % 60, tzinfo=UTC) for i in range(100)],
            "symbol": ["ES"] * 100,
            "tf": ["5m"] * 100,
            "test_score": [i / 100.0 for i in range(100)],
            "pnl_r": [i / 100.0 + 0.01 for i in range(100)],  # Slight noise
            "hmm_regime": [0] * 100,
        }
    )

    # Test with strict alpha (Bonferroni for 5 tests)
    result_strict = validate_backtest_results(
        data, field_name="test_score", min_ic=0.05, alpha=0.01, min_n=30
    )

    # Test with lenient alpha (no correction)
    result_lenient = validate_backtest_results(
        data, field_name="test_score", min_ic=0.05, alpha=0.05, min_n=30
    )

    # Both should pass because IC is high
    assert result_strict.passed is True
    assert result_lenient.passed is True


def test_validate_min_n_threshold():
    """Test that min_n threshold is enforced."""
    # Create small dataset
    data = pd.DataFrame(
        {
            "ts": [datetime(2026, 1, 1, 12 + i, 0, tzinfo=UTC) for i in range(10)],
            "symbol": ["ES"] * 10,
            "tf": ["5m"] * 10,
            "test_score": [i / 10.0 for i in range(10)],
            "pnl_r": [i / 10.0 for i in range(10)],
            "hmm_regime": [0] * 10,
        }
    )

    result = validate_backtest_results(
        data, field_name="test_score", min_ic=0.05, alpha=0.01, min_n=30
    )

    # Should fail due to insufficient sample size
    assert result.n == 10
    assert result.passed is False


def test_validate_missing_field():
    """Test validation when field_name doesn't exist in DataFrame."""
    data = pd.DataFrame(
        {
            "ts": [datetime(2026, 1, 1, 12, 0, tzinfo=UTC)],
            "symbol": ["ES"],
            "tf": ["5m"],
            "wrong_field": [0.5],
            "pnl_r": [0.02],
            "hmm_regime": [0],
        }
    )

    result = validate_backtest_results(
        data, field_name="test_score", min_ic=0.05, alpha=0.01, min_n=30
    )

    # Should handle gracefully with empty result
    assert result.n == 0
    assert result.passed is False


def test_validate_all_null_pnl_r():
    """Test validation when all pnl_r values are null."""
    data = pd.DataFrame(
        {
            "ts": [datetime(2026, 1, 1, i // 60, i % 60, tzinfo=UTC) for i in range(100)],
            "symbol": ["ES"] * 100,
            "tf": ["5m"] * 100,
            "test_score": [i / 100.0 for i in range(100)],
            "pnl_r": [None] * 100,  # All null
            "hmm_regime": [0] * 100,
        }
    )

    result = validate_backtest_results(
        data, field_name="test_score", min_ic=0.05, alpha=0.01, min_n=30
    )

    # Should filter out null pnl_r and return empty
    assert result.n == 0
    assert result.passed is False
