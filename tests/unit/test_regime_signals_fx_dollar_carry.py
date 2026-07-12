"""Unit tests for fx_dollar_carry signal module. CI-clean: no DB, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

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
        assert len(tiers2) >= 1


class TestProbKeys:
    def test_prob_keys_are_tuple_of_two(self):
        assert len(PROB_KEYS) == 2
