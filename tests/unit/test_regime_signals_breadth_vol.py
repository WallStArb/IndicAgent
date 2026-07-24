"""Unit tests for breadth_vol signal module. CI-clean: no DB, no network.

Includes the mandatory causal-rank regression test (RESEARCH.md Pitfall 1 / Wave 0
gap) mirroring test_vix_pct_rank_causal_property from
tests/unit/services/test_equity_regime_model_causal.py, plus _tf_window value tests
mirroring that same file's test_tf_window_* tests.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.breadth_vol import (
    PROB_KEYS,
    _compute_breadth,
    _compute_vix_pct_rank,
    build_tiers,
    compute,
)
from src.intelligence.regime_signals.tf_window import _tf_window

_UTC = pd.Timestamp("2020-01-01", tz="UTC")


def _make_bars(symbol: str, closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="1D")
    return pd.DataFrame({"timestamp": ts, "close": closes})


def _rising_bars(n: int, start: float = 100.0) -> list[float]:
    return [start + i * 0.1 for i in range(n)]


def _flat_bars(n: int, val: float = 100.0) -> list[float]:
    return [val] * n


class TestComputeReturnShape:
    def test_returns_two_series(self):
        n = 600
        ref_bars = {
            "SPY": _make_bars("SPY", _rising_bars(n)),
            "QQQ": _make_bars("QQQ", _rising_bars(n, 50.0)),
        }
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.40,
            "breadth_bull": 0.60,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        result = compute(ref_bars, params)
        assert result is not None
        s1, s2 = result
        assert isinstance(s1, pd.Series)
        assert isinstance(s2, pd.Series)
        assert len(s1) == n
        assert len(s2) == n

    def test_returns_none_when_spy_missing(self):
        ref_bars = {"QQQ": _make_bars("QQQ", _rising_bars(300))}
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.40,
            "breadth_bull": 0.60,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        result = compute(ref_bars, params)
        assert result is None

    def test_warmup_bars_are_nan(self):
        n = 600
        ref_bars = {"SPY": _make_bars("SPY", _rising_bars(n))}
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.40,
            "breadth_bull": 0.60,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        s1, s2 = compute(ref_bars, params)
        # VIX series warmup = realized_vol_window (20) + vix_z_window (252) - 1 = 271 bars
        assert s1.iloc[:271].isna().all()
        assert s1.iloc[272:].notna().any()


class TestBreadthSignal:
    """_compute_breadth (raw fraction) tests -- unaffected by the causal-rank fix, since
    compute()'s final output is now this raw fraction's causal expanding rank, not the raw
    fraction itself. See TestBreadthPctRank for the rank-transformed compute() output."""

    def test_all_above_200ma_returns_near_one(self):
        # Strongly rising series: all symbols above their 200MA after warmup
        n = 500
        closes = [100.0 + i for i in range(n)]  # steadily rising
        ref_bars = {
            "SPY": _make_bars("SPY", closes),
            "QQQ": _make_bars("QQQ", closes),
        }
        breadth = _compute_breadth(ref_bars, ma_window=200)
        valid = breadth.dropna()
        assert (valid > 0.9).all(), f"Expected breadth near 1.0, got min={valid.min():.2f}"

    def test_all_below_200ma_returns_near_zero(self):
        # Strongly falling series: all symbols below their 200MA after warmup
        n = 500
        closes = [500.0 - i for i in range(n)]  # steadily falling
        ref_bars = {
            "SPY": _make_bars("SPY", closes),
            "QQQ": _make_bars("QQQ", closes),
        }
        breadth = _compute_breadth(ref_bars, ma_window=200)
        valid = breadth.dropna()
        assert (valid < 0.1).all(), f"Expected breadth near 0.0, got max={valid.max():.2f}"


class TestBreadthPctRank:
    """compute()'s second return value is now a causal expanding percentile rank of the raw
    breadth fraction (mirroring vix_pct's own treatment), not the raw fraction itself -- fixes
    todo 092's population-imbalance finding (median raw breadth_frac ~0.70, far from the old
    fixed 0.40/0.60 cuts' implied center of 0.50)."""

    def test_breadth_output_is_bounded_rank_not_raw_fraction(self):
        # A breadth series with real cross-sectional variation (not saturated at 0 or 1) --
        # the raw fraction and its causal rank must differ once enough history accumulates.
        n = 400
        rng = np.random.default_rng(3)
        base = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, size=n)))
        ref_bars = {
            "SPY": _make_bars("SPY", list(base * 1.02)),
            "B": _make_bars("B", list(base * 0.98)),
            "C": _make_bars("C", list(base)),
        }
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.33,
            "breadth_bull": 0.67,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        _, breadth_pct = compute(ref_bars, params)
        raw = _compute_breadth(ref_bars, ma_window=200)
        valid_pct = breadth_pct.dropna()
        assert len(valid_pct) > 0
        assert (valid_pct >= 0.0).all() and (valid_pct <= 1.0).all()
        # The rank series must not be byte-identical to the raw fraction series (that would
        # mean the rank transform silently didn't run).
        common_idx = valid_pct.index.intersection(raw.dropna().index)
        assert not np.allclose(valid_pct.loc[common_idx].to_numpy(), raw.loc[common_idx].to_numpy())


class TestBuildTiers:
    def test_returns_two_tier_lists(self):
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.40,
            "breadth_bull": 0.60,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        t1, t2 = build_tiers(params)
        assert len(t1) == 3  # low, mid, high
        assert len(t2) == 3  # bear, neutral, bull

    def test_tier_names(self):
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.40,
            "breadth_bull": 0.60,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        t1, t2 = build_tiers(params)
        assert [n for n, _ in t1] == ["low", "mid", "high"]
        assert [n for n, _ in t2] == ["bear", "neutral", "bull"]

    def test_last_tier_upper_bound_is_inf(self):
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.40,
            "breadth_bull": 0.60,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        t1, t2 = build_tiers(params)
        assert t1[-1][1] == float("inf")
        assert t2[-1][1] == float("inf")


class TestProbKeys:
    def test_prob_keys_are_correct(self):
        # Renamed from "breadth_frac" -> "breadth_pct": compute()'s second series is now a
        # causal expanding percentile rank (mirroring vix_pct's own naming/treatment), not
        # the raw fraction.
        assert PROB_KEYS == ("vix_pct", "breadth_pct")


# ---------------------------------------------------------------------------
# _tf_window value tests (mirrors test_equity_regime_model_causal.py::test_tf_window_*)
# ---------------------------------------------------------------------------


def test_tf_window_5m():
    """_tf_window(200, '5m') must return 15600 (200 * 78 bars/day)."""
    assert _tf_window(200, "5m") == 15600


def test_tf_window_1h():
    """_tf_window(252, '1h') must return 1764 (252 * 7 bars/day)."""
    assert _tf_window(252, "1h") == 1764


def test_tf_window_1d():
    """_tf_window for 1d returns unchanged (1 bar/day)."""
    assert _tf_window(200, "1d") == 200


def test_tf_window_15m():
    """_tf_window(1, '15m') must return 26 (1 * 26 bars/day)."""
    assert _tf_window(1, "15m") == 26


# ---------------------------------------------------------------------------
# causal-property regression test (mirrors
# test_equity_regime_model_causal.py::test_vix_pct_rank_causal_property)
# ---------------------------------------------------------------------------


def _make_spy_series(n: int, base: float = 100.0, seed: int = 42) -> pd.Series:
    """Generate a deterministic SPY close-price pd.Series indexed by timestamp."""
    rng = np.random.default_rng(seed)
    log_returns = rng.normal(0.0, 0.01, size=n)
    closes = base * np.exp(np.cumsum(log_returns))
    base_dt = datetime(2020, 1, 2, 9, 30, tzinfo=UTC)
    ts = [base_dt + timedelta(days=i) for i in range(n)]
    return pd.Series(closes, index=pd.DatetimeIndex(ts), dtype=float)


def test_vix_pct_rank_causal_property():
    """Appending a large future value must NOT change earlier ranks.

    A causal bisect implementation is immune to look-ahead bias: each position's
    rank is computed from only the values seen before it. This is the single
    most important correctness threat in this plan (T-144-02-LA) and is the
    mandatory Wave 0 gap flagged in RESEARCH.md.

    Protocol:
      1. Compute ranks on N bars.
      2. Append one very large value and compute ranks on N+1 bars.
      3. The earlier valid (non-NaN) ranks common to both series must be identical.
    """
    n = 50
    spy_close_n = _make_spy_series(n, seed=7)

    # Small windows so warmup clears within the test's bar count.
    ranks_n = _compute_vix_pct_rank(spy_close_n, realized_vol_window=3, vix_z_window=5)

    # Append an enormous outlier.
    outlier_ts = spy_close_n.index[-1] + timedelta(days=1)
    outlier_val = spy_close_n.iloc[-1] * 100.0  # 100x price spike
    spy_close_n1 = pd.concat([spy_close_n, pd.Series([outlier_val], index=[outlier_ts])])

    ranks_n1 = _compute_vix_pct_rank(spy_close_n1, realized_vol_window=3, vix_z_window=5)

    valid_n = ranks_n.dropna()
    valid_n1 = ranks_n1.iloc[:n].dropna()

    assert len(valid_n) > 0, "No valid ranks in N-bar series -- warmup not satisfied"
    assert len(valid_n1) > 0, "No valid ranks in N+1-bar series -- warmup not satisfied"

    common_idx = valid_n.index.intersection(valid_n1.index)
    assert len(common_idx) > 0, "No common non-NaN timestamps"

    for ts in common_idx:
        r_original = valid_n.loc[ts]
        r_extended = valid_n1.loc[ts]
        assert abs(r_original - r_extended) < 1e-9, (
            f"Causal property VIOLATED at {ts}: "
            f"rank changed from {r_original:.6f} to {r_extended:.6f} "
            f"after appending a future outlier. "
            f"This indicates look-ahead bias in _compute_vix_pct_rank."
        )
