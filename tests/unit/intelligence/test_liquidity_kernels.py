"""Spread-estimator kernels (todo 553) and the Amihud zero-close guard (todo 390).

Hand-computed values on small arrays, the NaN contract (no_fill), and the declared memory held
by the registry's causality probe and memory check.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.features.contract.causality_probe import causality_probe, memory_check
from src.intelligence.features.contract.registry import default_registry, feature_memory_bars
from src.intelligence.features.kernels.liquidity import (
    _high_low_spread_series_full,
    _roll_spread_series_full,
)

_K = 3.0 - 2.0 * math.sqrt(2.0)


def _cs_pair(h0: float, l0: float, h1: float, l1: float) -> float:
    """Corwin-Schultz eq. 14 and 18 for one pair of already overnight-adjusted bars."""
    beta = math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2
    gamma = math.log(max(h0, h1) / min(l0, l1)) ** 2
    alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / _K - math.sqrt(gamma / _K)
    return 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))


def _hl(highs, lows, closes, window):
    return _high_low_spread_series_full(
        np.array(highs, float), np.array(lows, float), np.array(closes, float), window
    )


# ---------------------------------------------------------------------------
# Corwin-Schultz high_low_spread
# ---------------------------------------------------------------------------


def test_high_low_spread_equal_bars_give_the_quoted_spread_exactly():
    """Two identical bars H=101, L=99: with k = ln(101/99), beta = 2k^2 and gamma = k^2, so
    alpha = sqrt(2) k / (sqrt(2) - 1) - k / (sqrt(2) - 1) = k and S = 2 (e^k - 1) / (1 + e^k)
    = 2 (2/99) / (200/99) = 0.02: the 2-wide quote around 100."""
    out = _hl([101.0, 101.0], [99.0, 99.0], [100.0, 100.0], window=1)
    assert math.isnan(out[0])
    assert out[1] == pytest.approx(0.02, abs=1e-12)


def test_high_low_spread_window_mean_of_pairs():
    highs = [101.0, 101.0, 100.5]
    lows = [99.0, 99.0, 99.5]
    closes = [100.0, 100.0, 100.0]
    out = _hl(highs, lows, closes, window=2)
    first = _cs_pair(101.0, 99.0, 101.0, 99.0)
    second = _cs_pair(101.0, 99.0, 100.5, 99.5)
    assert np.isnan(out[:2]).all()
    assert out[2] == pytest.approx((max(first, 0.0) + max(second, 0.0)) / 2.0, abs=1e-15)


def test_high_low_spread_overnight_gap_up_lowers_the_second_bar():
    """Bar 1's low 108.5 is above bar 0's close 99.5: both of bar 1's prices drop by 9, to
    101.5/99.5, which is the same pair as an ungapped bar 1 of 101.5/99.5."""
    gapped = _hl([101.0, 110.5], [99.0, 108.5], [99.5, 110.0], window=1)
    plain = _hl([101.0, 101.5], [99.0, 99.5], [99.5, 101.0], window=1)
    assert _cs_pair(101.0, 99.0, 101.5, 99.5) > 0.0
    assert gapped[1] == pytest.approx(_cs_pair(101.0, 99.0, 101.5, 99.5), abs=1e-15)
    assert gapped[1] == pytest.approx(plain[1], abs=1e-15)
    # Unadjusted, the 9-point gap would read as range and drive the estimate to 0.
    assert _cs_pair(101.0, 99.0, 110.5, 108.5) < 0.0


def test_high_low_spread_overnight_gap_down_raises_the_second_bar():
    """Bar 1's high 91 is below bar 0's close 100: both of bar 1's prices rise by 9, to 100/98."""
    out = _hl([101.0, 91.0], [99.0, 89.0], [100.0, 90.0], window=1)
    assert out[1] == pytest.approx(max(_cs_pair(101.0, 99.0, 100.0, 98.0), 0.0), abs=1e-15)


def test_high_low_spread_negative_estimate_is_zero_not_nan():
    """Bar ranges of 1% each but a 2% two-bar range: alpha < 0, so S < 0, set to 0 (paper's
    convention) and kept in the average."""
    assert _cs_pair(101.0, 100.0, 102.0, 101.0) < 0.0
    out = _hl([101.0, 102.0], [100.0, 101.0], [101.0, 101.5], window=1)
    assert out[1] == 0.0
    # Kept in the window mean: half of the positive pair's value.
    out = _hl([101.0, 102.0, 102.0], [100.0, 101.0, 101.0], [101.0, 101.5, 101.5], window=2)
    assert out[2] == pytest.approx(_cs_pair(102.0, 101.0, 102.0, 101.0) / 2.0, abs=1e-15)


def test_high_low_spread_nan_contract():
    highs = np.array([101.0, 101.0, 101.0, 101.0, 101.0, 101.0])
    lows = np.array([99.0, 99.0, 0.0, 99.0, 99.0, 99.0])
    closes = np.full(6, 100.0)
    out = _high_low_spread_series_full(highs, lows, closes, 2)
    # rows < window are NaN; the pairs (1, 2) and (2, 3) read the zero low; a window holding one
    # of them is NaN (rows 2, 3, 4); row 5 averages pairs (3, 4) and (4, 5), both clean.
    assert np.isnan(out[:5]).all()
    assert out[5] == pytest.approx(0.02, abs=1e-12)
    assert not np.isinf(out).any()


def test_high_low_spread_zero_close_makes_the_next_pair_nan():
    """A close == 0 bar (todo 390's data condition) puts the next bar's adjusted low at 0."""
    out = _hl([101.0, 101.0, 101.0], [99.0, 99.0, 99.0], [100.0, 0.0, 100.0], window=1)
    assert out[1] == pytest.approx(0.02, abs=1e-12)
    assert math.isnan(out[2])


def test_high_low_spread_nan_prior_close_is_nan_not_an_unadjusted_pair():
    """Bar 1 gaps up past a NaN close: the overnight adjustment cannot be made, so the pair is
    NaN rather than read unadjusted (which would floor it to 0)."""
    out = _hl([101.0, 110.5, 111.0], [99.0, 108.5, 109.0], [np.nan, 110.0, 110.5], window=1)
    assert math.isnan(out[1])
    assert out[2] == pytest.approx(max(_cs_pair(110.5, 108.5, 111.0, 109.0), 0.0), abs=1e-15)


def test_high_low_spread_short_series_is_all_nan():
    assert np.isnan(_hl([101.0], [99.0], [100.0], window=1)).all()
    assert np.isnan(_hl([101.0, 101.0], [99.0, 99.0], [100.0, 100.0], window=2)).all()


# ---------------------------------------------------------------------------
# Roll roll_spread
# ---------------------------------------------------------------------------


def test_roll_spread_bid_ask_bounce_hand_value():
    """Closes bounce 100, 101, 100, 101, 100: r = a, -a, a, -a with a = ln(1.01). At t = 4 with
    window 3, x = (-a, a, -a), y = (a, -a, a); deviations (-2a/3, 4a/3, -2a/3) and
    (2a/3, -4a/3, 2a/3) give products summing to -24a^2/9, so cov = -4a^2/3 (ddof 1) and
    S = 2 sqrt(4a^2/3) = 4a / sqrt(3)."""
    a = math.log(1.01)
    out = _roll_spread_series_full(np.array([100.0, 101.0, 100.0, 101.0, 100.0]), 3)
    assert np.isnan(out[:4]).all()
    assert out[4] == pytest.approx(4.0 * a / math.sqrt(3.0), rel=1e-12)


def test_roll_spread_non_negative_covariance_is_nan():
    # flat closes: every change is exactly 0, so the covariance is exactly 0
    assert np.isnan(_roll_spread_series_full(np.full(8, 100.0), 3)).all()
    # trending returns (positive serial covariance)
    r = np.array([0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
    closes = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(r)]))
    assert np.isnan(_roll_spread_series_full(closes, 3)).all()


def test_roll_spread_zero_close_window_is_nan():
    closes = np.array([100.0, 101.0, 100.0, 0.0, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0])
    out = _roll_spread_series_full(closes, 3)
    # row t reads closes t - 4 .. t: rows 4..7 hold close 3 (rows < 4 are warmup); rows 8 and 9
    # read a clean bounce again
    assert np.isnan(out[:8]).all()
    assert out[8] == pytest.approx(4.0 * math.log(1.01) / math.sqrt(3.0), rel=1e-12)
    assert not np.isinf(out).any()


def test_roll_spread_refuses_a_window_below_two():
    with pytest.raises(ValueError):
        _roll_spread_series_full(np.ones(10), 1)


# ---------------------------------------------------------------------------
# Registry contract: declared memory and causality
# ---------------------------------------------------------------------------


def _bars(n: int, seed: int = 7, zero_close_at: int | None = None) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    # Price near 1 and volume 1 to 10, so the Amihud raw value (|r| / dollar volume) varies
    # well above the z-score's absolute std floor and its z-scores are not all 0.
    closes = np.cumprod(1.0 + rng.normal(0, 0.01, n))
    spread = closes * rng.uniform(0.001, 0.01, n)
    opens = closes * (1.0 + rng.normal(0, 0.004, n))
    highs = np.maximum(closes + spread, np.maximum(opens, closes))
    lows = np.minimum(closes - spread, np.minimum(opens, closes))
    if zero_close_at is not None:
        closes[zero_close_at] = 0.0
    return {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": rng.uniform(1.0, 10.0, n),
        "volume_basis": np.ones(n, dtype=np.int64),
    }


_CONFIG = SimpleNamespace(
    high_low_spread_window=21,
    roll_spread_window=60,
    amihud_zscore_window=40,
    amihud_min_valid_fraction=0.8,
)
_ROWS = np.array([0, 5, 21, 22, 60, 61, 62, 100, 150, 199])


@pytest.mark.parametrize("name", ["high_low_spread", "roll_spread", "amihud_illiq_z"])
@pytest.mark.parametrize("zero_close_at", [None, 80])
def test_kernel_is_causal_and_honors_its_declared_memory(name, zero_close_at):
    kernel = default_registry().by_name(name)
    inputs = _bars(200, zero_close_at=zero_close_at)
    causality_probe(kernel, inputs, _CONFIG, _ROWS)
    memory_check(kernel, inputs, _CONFIG, _ROWS)


def test_declared_memory_values():
    registry = default_registry()
    assert feature_memory_bars("high_low_spread", _CONFIG, registry) == 21
    assert feature_memory_bars("roll_spread", _CONFIG, registry) == 61
    assert registry.by_name("high_low_spread").inputs == ("high", "low", "close")
    assert registry.by_name("roll_spread").inputs == ("close",)
    assert not registry.by_name("high_low_spread").path_dependent
    assert not registry.by_name("roll_spread").path_dependent


def test_outputs_are_finite_or_nan_on_clean_bars():
    inputs = _bars(400)
    hl = _high_low_spread_series_full(inputs["high"], inputs["low"], inputs["close"], 21)
    roll = _roll_spread_series_full(inputs["close"], 60)
    assert np.isfinite(hl[21:]).all() and np.isnan(hl[:21]).all()
    assert (hl[21:] >= 0.0).all()
    assert not np.isinf(roll).any() and np.isnan(roll[:61]).all()
    finite = roll[np.isfinite(roll)]
    assert (finite > 0.0).all()
