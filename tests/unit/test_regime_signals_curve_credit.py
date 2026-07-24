"""Unit tests for curve_credit signal module. CI-clean: no DB, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.curve_credit import (
    PROB_KEYS,
    _log_return_spread,
    _rolling_z,
    build_tiers,
    compute,
)

_UTC = pd.Timestamp("2020-01-01", tz="UTC")

_REQUIRED_SYMBOLS = ["TLT", "SHY", "HYG", "LQD"]


def _make_bars(closes) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="1D")
    return pd.DataFrame({"timestamp": ts, "close": closes})


def _rising(n: int, start: float = 100.0) -> list[float]:
    return [start + i * 0.01 for i in range(n)]


def _falling(n: int, start: float = 100.0) -> list[float]:
    return [start - i * 0.01 for i in range(n)]


def _default_params() -> dict:
    return {
        "curve_window": 20,
        "credit_window": 20,
        "steep_threshold": 0.67,
        "inverted_threshold": 0.33,
        "credit_tight_threshold": 0.5,
    }


class TestComputeBasic:
    def test_returns_none_when_symbol_missing(self):
        ref_bars = {s: _make_bars(_rising(200)) for s in ["TLT", "SHY", "HYG"]}  # LQD missing
        result = compute(ref_bars, _default_params())
        assert result is None

    def test_returns_two_aligned_series(self):
        n = 200
        ref_bars = {s: _make_bars(_rising(n)) for s in _REQUIRED_SYMBOLS}
        result = compute(ref_bars, _default_params())
        assert result is not None
        s1, s2 = result
        assert len(s1) == len(s2)
        assert isinstance(s1, pd.Series)
        assert isinstance(s2, pd.Series)

    def test_warmup_bars_are_nan(self):
        n = 300
        ref_bars = {s: _make_bars(_rising(n)) for s in _REQUIRED_SYMBOLS}
        s1, s2 = compute(ref_bars, _default_params())
        # warmup = 2 * window - 1 = 39 bars (window=20)
        assert s1.iloc[:39].isna().all()


class TestSignalDirection:
    """compute() now returns a causal expanding percentile rank (todo 092), not the raw
    z-score -- a persistently one-directional spread should rank near its own historical
    high (close to 1.0, above its own median 0.5), not simply "> 0"."""

    def test_rising_tlt_falling_shy_positive_curve_z(self):
        """TLT rising faster than SHY -> positive spread -> positive curve_z at end.

        Tests _log_return_spread's subtraction order directly (TLT - SHY), bypassing
        compute()'s rank transform -- a monotonic rank transform preserves ordering, so this
        is the correct, robust place to check direction; asserting on the final RANKED value
        instead is fragile (a rolling z-score's causal rank position near a plateau is
        sensitive to floating-point-level noise, verified empirically while writing this
        test -- not a meaningful direction signal)."""
        n = 300
        spread = _log_return_spread(_make_bars(_rising(n, 100.0)), _make_bars(_falling(n, 100.0)))
        curve_z = _rolling_z(spread, window=20)
        valid = curve_z.dropna()
        assert valid.iloc[-1] > 0, f"Expected positive curve_z, got {valid.iloc[-1]:.4f}"

    def test_hyg_rising_lqd_falling_positive_credit_z(self):
        """HYG outperforming LQD -> positive credit spread -> positive credit_z (tight).

        See test_rising_tlt_falling_shy_positive_curve_z's docstring for why this tests the
        raw z-score directly rather than compute()'s ranked output."""
        n = 300
        spread = _log_return_spread(_make_bars(_rising(n, 80.0)), _make_bars(_falling(n, 80.0)))
        credit_z = _rolling_z(spread, window=20)
        valid = credit_z.dropna()
        assert valid.iloc[-1] > 0, f"Expected positive credit_z, got {valid.iloc[-1]:.4f}"

    def test_compute_output_bounded_zero_to_one(self):
        n = 300
        ref_bars = {
            "TLT": _make_bars(_rising(n, 100.0)),
            "SHY": _make_bars(_falling(n, 100.0)),
            "HYG": _make_bars(_rising(n, 80.0)),
            "LQD": _make_bars(_falling(n, 80.0)),
        }
        s1, s2 = compute(ref_bars, _default_params())
        v1, v2 = s1.dropna(), s2.dropna()
        assert (v1 >= 0.0).all() and (v1 <= 1.0).all()
        assert (v2 >= 0.0).all() and (v2 <= 1.0).all()


class TestBuildTiers:
    def test_curve_has_three_tiers(self):
        t1, t2 = build_tiers(_default_params())
        assert len(t1) == 3
        assert [n for n, _ in t1] == ["inverted", "flat", "steep"]

    def test_credit_has_two_tiers(self):
        t1, t2 = build_tiers(_default_params())
        assert len(t2) == 2
        assert [n for n, _ in t2] == ["wide", "tight"]

    def test_last_upper_bounds_are_inf(self):
        t1, t2 = build_tiers(_default_params())
        assert t1[-1][1] == float("inf")
        assert t2[-1][1] == float("inf")

    def test_thresholds_from_params(self):
        params = {**_default_params(), "steep_threshold": 0.8, "inverted_threshold": 0.2}
        t1, _ = build_tiers(params)
        assert t1[0][1] == 0.2  # inverted upper bound
        assert t1[1][1] == 0.8  # flat upper bound


class TestProbKeys:
    def test_prob_keys(self):
        # Renamed from ("curve_z", "credit_z") -- compute() now returns a causal expanding
        # percentile rank (todo 092), not the raw rolling z-score.
        assert PROB_KEYS == ("curve_pct", "credit_pct")
