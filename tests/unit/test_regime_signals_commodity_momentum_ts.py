"""Unit tests for commodity_momentum_ts signal module. CI-clean: no DB, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.commodity_momentum_ts import PROB_KEYS, build_tiers, compute

_UTC = pd.Timestamp("2020-01-01", tz="UTC")


def _make_bars(closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="5min")
    return pd.DataFrame({"timestamp": ts, "close": closes})


class TestComputeShape:
    def test_returns_two_series_same_length(self):
        n, window = 200, 60
        bars = {
            "USO": _make_bars([100 + i * 0.1 for i in range(n)]),
            "UNG": _make_bars([50 + i * 0.05 for i in range(n)]),
        }
        params = {"momentum_window": window, "primary_threshold": 0.75}
        s1, s2 = compute(bars, params)
        assert len(s1) == n
        assert len(s2) == n

    def test_warmup_bars_are_nan(self):
        n, window = 200, 60
        bars = {"USO": _make_bars([100.0] * n)}
        params = {"momentum_window": window, "primary_threshold": 0.75}
        s1, _ = compute(bars, params)
        assert s1.iloc[:window].isna().all()

    def test_rising_group_positive_median(self):
        # NOTE: constant absolute price increments (linear ramp) produce
        # monotonically DECREASING log-returns (diminishing percentage gain as price
        # rises) — a rolling z-score of such returns is negative even though the
        # price itself is rising. The momentum_z signal measures recent-return
        # magnitude relative to its own trailing distribution, so genuinely testing
        # "positive momentum" requires ACCELERATING (increasing) log-returns, not
        # merely a rising price. Construct closes from a deliberately increasing
        # log-return sequence.
        n, window = 200, 60
        log_ret_ramp = np.arange(n, dtype=float) * 0.001
        bars = {}
        for sym in ["USO", "UNG", "XOP"]:
            closes = np.concatenate([[100.0], 100.0 * np.exp(np.cumsum(log_ret_ramp[1:]))])
            bars[sym] = _make_bars(list(closes))
        params = {"momentum_window": window, "primary_threshold": 0.75}
        s1, _ = compute(bars, params)
        assert s1.iloc[window:].median() > 0

    def test_empty_ref_bars_returns_none(self):
        params = {"momentum_window": 60, "primary_threshold": 0.75}
        assert compute({}, params) is None


class TestBuildTiers:
    def test_returns_two_tier_lists(self):
        tiers1, tiers2 = build_tiers({"primary_threshold": 0.75})
        assert len(tiers1) >= 2
        assert len(tiers2) >= 2


class TestProbKeys:
    def test_prob_keys_are_tuple_of_two(self):
        assert len(PROB_KEYS) == 2
