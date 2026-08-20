"""Unit tests for fx_dollar_carry signal module. CI-clean: no DB, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

from services.cross_sectional_regime_model import _assert_ascending_tiers, _bucket
from src.intelligence.regime_signals.fx_dollar_carry import (
    PROB_KEYS,
    REFERENCE_SYMBOLS,
    build_tiers,
    compute,
)

_UTC = pd.Timestamp("2020-01-01", tz="UTC")


def _make_bars(closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="5min")
    return pd.DataFrame({"timestamp": ts, "close": closes})


class TestComputeShape:
    def test_returns_two_series(self):
        n, window = 200, 60
        bars = {
            "UUP": _make_bars([25 + i * 0.01 for i in range(n)]),
            "HYG": _make_bars([80 + i * 0.05 for i in range(n)]),
            "FXE": _make_bars([105 - i * 0.01 for i in range(n)]),
        }
        params = {
            "momentum_window": window,
            "dollar_strong_threshold": 0.5,
            "carry_risk_on_threshold": 0.0,
        }
        s1, s2 = compute(bars, params)
        assert len(s1) == n
        assert len(s2) == n

    def test_warmup_nan(self):
        n, window = 200, 60
        bars = {"UUP": _make_bars([25.0] * n), "HYG": _make_bars([80.0] * n)}
        params = {
            "momentum_window": window,
            "dollar_strong_threshold": 0.5,
            "carry_risk_on_threshold": 0.0,
        }
        s1, _ = compute(bars, params)
        assert s1.iloc[:window].isna().all()

    def test_missing_uup_returns_none(self):
        bars = {"FXE": _make_bars([105.0] * 200)}
        params = {
            "momentum_window": 60,
            "dollar_strong_threshold": 0.5,
            "carry_risk_on_threshold": 0.0,
        }
        assert compute(bars, params) is None


class TestReferenceSymbols:
    def test_uup_and_hyg_declared(self):
        assert "UUP" in REFERENCE_SYMBOLS
        assert "HYG" in REFERENCE_SYMBOLS


class TestBuildTiers:
    def test_returns_two_tier_lists(self):
        tiers1, tiers2 = build_tiers(
            {"dollar_strong_threshold": 0.5, "carry_risk_on_threshold": 0.0}
        )
        assert len(tiers1) >= 2
        # NOTE: pre-fix tiers2 was a single-entry list ([("risk_on", thresh)]) that
        # made "risk_off" permanently unreachable (todo 335) -- `>= 1` would pass on
        # that broken shape too. Requiring >= 2 here is itself a regression guard;
        # the real reachability check is test_all_carry_labels_reachable below.
        assert len(tiers2) >= 2

    def test_tiers_ascending_by_upper_bound(self):
        """Neither the old `len(...) >= N` assertions nor _bucket()'s own tests
        (which feed it hand-constructed correct tiers) could catch this class of
        bug (see todo 335 / _assert_ascending_tiers' own docstring)."""
        tiers1, tiers2 = build_tiers(
            {"dollar_strong_threshold": 0.5, "carry_risk_on_threshold": 0.0}
        )
        _assert_ascending_tiers(tiers1, "fx_dollar_carry", "tiers1")
        _assert_ascending_tiers(tiers2, "fx_dollar_carry", "tiers2")

    def test_all_dollar_strength_labels_reachable(self):
        tiers1, _ = build_tiers({"dollar_strong_threshold": 0.5, "carry_risk_on_threshold": 0.0})
        vals = np.array([-1.0, 1.0])
        result = _bucket(vals, tiers1)
        assert set(result) == {"weak_dollar", "strong_dollar"}

    def test_all_carry_labels_reachable(self):
        _, tiers2 = build_tiers({"dollar_strong_threshold": 0.5, "carry_risk_on_threshold": 0.0})
        vals = np.array([-1.0, 1.0])
        result = _bucket(vals, tiers2)
        assert set(result) == {"risk_off", "risk_on"}


class TestProbKeys:
    def test_prob_keys_are_tuple_of_two(self):
        assert len(PROB_KEYS) == 2
