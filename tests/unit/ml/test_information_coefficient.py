"""Unit tests for the Information Coefficient computation module."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.ml.information_coefficient import (
    IC_MIN_SAMPLE_SIZE,
    IC_P_VALUE_THRESHOLD,
    ICResult,
    compute_ic,
    is_ic_significant,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pairs(n: int, win_fraction: float = 0.6, seed: int = 42):
    """Generate synthetic (confidence, pnl_r) pairs with controlled IC.

    High confidence -> high pnl_r, low confidence -> low pnl_r, giving positive IC.
    """
    rng = np.random.default_rng(seed)
    wins = int(n * win_fraction)
    pnl_rs = [2.0] * wins + [-1.0] * (n - wins)
    conf_win = rng.uniform(0.6, 0.9, wins)
    conf_loss = rng.uniform(0.3, 0.6, n - wins)
    confidences = list(conf_win) + list(conf_loss)
    return confidences, pnl_rs


# ---------------------------------------------------------------------------
# compute_ic
# ---------------------------------------------------------------------------


def test_compute_ic_returns_none_below_min_sample():
    """IC must return None when sample size < IC_MIN_SAMPLE_SIZE."""
    n = IC_MIN_SAMPLE_SIZE - 1
    ic, pv, count = compute_ic([0.7] * n, [1.0] * n)
    assert ic is None
    assert pv is None
    assert count == n


def test_compute_ic_exactly_min_sample():
    """IC should attempt computation at exactly IC_MIN_SAMPLE_SIZE samples."""
    conf, outcomes = _make_pairs(IC_MIN_SAMPLE_SIZE, win_fraction=0.7)
    ic, pv, n = compute_ic(conf, outcomes)
    assert n == IC_MIN_SAMPLE_SIZE
    # May or may not be significant at exactly 30 samples but should not be None
    # unless zero variance
    assert ic is not None or n < IC_MIN_SAMPLE_SIZE


def test_compute_ic_detects_positive_correlation():
    """IC should be positive when high confidence predicts wins."""
    conf, outcomes = _make_pairs(200, win_fraction=0.65)
    ic, pv, n = compute_ic(conf, outcomes)
    assert ic is not None
    assert ic > 0.0, f"Expected positive IC, got {ic}"
    assert n == 200


def test_compute_ic_noise_signal_large_n():
    """Random confidence with large N should produce near-zero IC."""
    rng = np.random.default_rng(99)
    n = 200
    conf = list(rng.uniform(0.3, 0.9, n))
    # Random pnl_r — no relationship to confidence
    pnl_rs = list(rng.uniform(-2.0, 2.0, n))
    ic, pv, n_used = compute_ic(conf, pnl_rs)
    assert n_used == n
    assert ic is not None


def test_compute_ic_skips_none_pnl_rs():
    """None pnl_rs (never_activated) must be excluded from IC computation."""
    conf = [0.7] * 50 + [0.3] * 50
    pnl_rs = [1.0] * 50 + [None] * 50
    ic, pv, n = compute_ic(conf, pnl_rs)
    # Only 50 resolved signals used
    assert n == 50


def test_compute_ic_zero_variance_confidence():
    """Zero-variance confidence array should return None (cannot compute correlation)."""
    n = 50
    conf = [0.7] * n  # All same value -> zero variance
    pnl_rs = [2.0] * 25 + [-1.0] * 25
    ic, pv, count = compute_ic(conf, pnl_rs)
    assert ic is None
    assert pv is None
    assert count == n


def test_compute_ic_zero_variance_pnl_r():
    """Zero-variance pnl_r array should return None (cannot compute correlation)."""
    n = 50
    conf = list(np.linspace(0.3, 0.9, n))
    pnl_rs = [1.0] * n  # All same value -> zero variance
    ic, pv, count = compute_ic(conf, pnl_rs)
    assert ic is None
    assert pv is None
    assert count == n


def test_compute_ic_returns_tuple_of_three():
    """compute_ic must always return a 3-tuple."""
    result = compute_ic([0.5] * 5, [1.0] * 5)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# is_ic_significant
# ---------------------------------------------------------------------------


def test_is_ic_significant_all_gates_pass():
    """All 3 gates must pass for is_ic_significant to return True."""
    assert is_ic_significant(0.10, 0.01, 50) is True


def test_is_ic_significant_p_value_too_high():
    """Fails when p-value >= IC_P_VALUE_THRESHOLD."""
    assert is_ic_significant(0.10, IC_P_VALUE_THRESHOLD, 50) is False


def test_is_ic_significant_ic_below_threshold():
    """Fails when IC score is below IC_NOISE_THRESHOLD."""
    assert is_ic_significant(0.04, 0.01, 50) is False


def test_is_ic_significant_n_too_low():
    """Fails when N < IC_MIN_SAMPLE_SIZE."""
    assert is_ic_significant(0.10, 0.01, IC_MIN_SAMPLE_SIZE - 1) is False


def test_is_ic_significant_none_ic():
    """Fails when IC score is None."""
    assert is_ic_significant(None, 0.01, 50) is False


def test_is_ic_significant_none_pvalue():
    """Fails when p-value is None."""
    assert is_ic_significant(0.10, None, 50) is False


def test_is_ic_significant_boundary_n():
    """Passes at exactly IC_MIN_SAMPLE_SIZE."""
    assert is_ic_significant(0.10, 0.01, IC_MIN_SAMPLE_SIZE) is True


# ---------------------------------------------------------------------------
# ICResult
# ---------------------------------------------------------------------------


def _make_ic_result(ic_score: float | None, ic_p: float | None, ic_n: int = 100, ic_sig: bool = True) -> ICResult:
    wins = 60
    return ICResult(
        setup_plugin="trad_Test",
        timeframe="1m",
        regime_type="trend",
        symbol=None,
        window_days=30,
        sample_size=100,
        wins=wins,
        win_rate=wins / 100,
        avg_pnl_r=0.5,
        ic_score=ic_score,
        ic_p_value=ic_p,
        ic_n=ic_n,
        ic_significant=ic_sig,
    )


def test_ic_result_grade_strong():
    r = _make_ic_result(0.22, 0.001)
    assert r.grade == "strong"


def test_ic_result_grade_meaningful():
    r = _make_ic_result(0.12, 0.001)
    assert r.grade == "meaningful"


def test_ic_result_grade_weak():
    r = _make_ic_result(0.07, 0.01)
    assert r.grade == "weak"


def test_ic_result_grade_noise_low_ic():
    r = _make_ic_result(0.02, 0.001, ic_sig=False)
    assert r.grade == "noise"


def test_ic_result_grade_noise_high_pvalue():
    r = _make_ic_result(0.10, 0.20, ic_sig=False)
    assert r.grade == "noise"


def test_ic_result_grade_insufficient_data():
    r = _make_ic_result(None, None)
    assert r.grade == "insufficient_data"


def test_ic_result_is_noise_when_no_ic():
    r = _make_ic_result(None, None)
    assert r.is_noise is True


def test_ic_result_is_not_noise_when_significant():
    r = _make_ic_result(0.10, 0.001)
    assert r.is_noise is False


def test_ic_result_is_noise_when_p_value_too_high():
    r = _make_ic_result(0.10, 0.10, ic_sig=False)
    assert r.is_noise is True


def test_ic_result_is_noise_when_ic_too_low():
    r = _make_ic_result(0.03, 0.001, ic_sig=False)
    assert r.is_noise is True


def test_ic_result_is_frozen():
    """ICResult must be immutable (frozen=True)."""
    r = _make_ic_result(0.10, 0.001)
    with pytest.raises(Exception):
        r.ic_score = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Continuous pnl_r IC tests
# ---------------------------------------------------------------------------


class TestComputeIcContinuous:
    """Tests for continuous pnl_r-based IC (replaces binary outcome coding)."""

    def _make_pairs(self, n, conf_high=0.8, conf_low=0.4, pnl_high=2.0, pnl_low=-1.0):
        """n/2 high-confidence wins + n/2 low-confidence losses."""
        half = n // 2
        confs = [conf_high] * half + [conf_low] * half
        pnls = [pnl_high] * half + [pnl_low] * half
        return confs, pnls

    def test_returns_none_when_insufficient_data(self):
        confs = [0.7] * (IC_MIN_SAMPLE_SIZE - 1)
        pnls = [1.0] * (IC_MIN_SAMPLE_SIZE - 1)
        ic, p, n = compute_ic(confs, pnls)
        assert ic is None
        assert p is None
        assert n == IC_MIN_SAMPLE_SIZE - 1

    def test_positive_ic_when_high_conf_correlates_with_high_pnl(self):
        confs, pnls = self._make_pairs(60)
        ic, p, n = compute_ic(confs, pnls)
        assert ic is not None
        assert ic > 0
        assert p < 0.05

    def test_negative_ic_when_high_conf_anticorrelates(self):
        confs, pnls = self._make_pairs(60, conf_high=0.8, pnl_high=-2.0,
                                        conf_low=0.4, pnl_low=2.0)
        ic, p, n = compute_ic(confs, pnls)
        assert ic is not None
        assert ic < 0

    def test_none_pnl_values_are_skipped(self):
        """never_activated signals (pnl_r=None) are excluded from IC."""
        confs = [0.8] * 20 + [0.4] * 20 + [0.9] * 10
        pnls = [2.0] * 20 + [-1.0] * 20 + [None] * 10  # 10 never_activated
        ic, p, n = compute_ic(confs, pnls)
        assert n == 40  # only 40 resolved pairs

    def test_all_losses_no_longer_produces_zero_variance(self):
        """With continuous pnl_r, varying loss magnitudes produce non-zero variance.

        This is the key regression: with binary coding, all losses mapped to -1.0
        (zero variance) -> IC was always None. With pnl_r, -0.5R and -3.0R differ.
        """
        confs = [0.8] * 30 + [0.4] * 30
        pnls = [-3.0] * 30 + [-0.5] * 30
        ic, p, n = compute_ic(confs, pnls)
        assert ic is not None
        assert n == 60
