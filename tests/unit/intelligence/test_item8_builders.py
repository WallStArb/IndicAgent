"""Builders behind the item-8 add-list columns (todo 584 D2): market residual, return
distribution, dividend yield. Daily grain; every statistic is NaN until its window fills."""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, date, datetime, timedelta

import numpy as np

from src.intelligence.features.kernels.distribution import build_distribution_series
from src.intelligence.features.kernels.dividend import (
    build_dividend_yield_series,
    reconciled_amounts,
)
from src.intelligence.features.kernels.residual import build_market_residual_series
from tests.unit.intelligence import kernel_parity_reference as ref

CONFIG = dataclasses.replace(
    ref.build_config(ref.load_manifest()["synthetic_config"]),
    factor_beta_window=10,
    market_residual_z_window=8,
    idiosyncratic_volatility_window=5,
    market_residual_lag1_acf_window=8,
    residual_beta_stability_window=4,
    max_daily_return_window=5,
    max_drawdown_window=10,
    downside_deviation_window=10,
    size_proxy_window=5,
    dividend_yield_window=5,
)
START = datetime(2024, 1, 2, tzinfo=UTC)


def _bars(closes, skip=()):
    return [
        {"ts": START + timedelta(days=i), "close": float(c), "high": c, "low": c, "volume": 1e6}
        for i, c in enumerate(closes)
        if i not in skip
    ]


def _walk(n, seed):
    return 100.0 * np.cumprod(1.0 + np.random.default_rng(seed).normal(0, 0.01, n))


def test_residual_is_nan_until_the_windows_fill():
    records = build_market_residual_series(_bars(_walk(60, 1)), _bars(_walk(60, 2)), "ABC", CONFIG)
    dates = sorted(records)

    def first_finite(field):
        return next(d for d in dates if not math.isnan(getattr(records[d], field)))

    # the residual needs a full beta window of returns; every statistic over it needs its own
    assert first_finite("market_residual_return") >= dates[CONFIG.factor_beta_window - 1]
    assert first_finite("market_residual_z") > first_finite("market_residual_return")
    assert first_finite("residual_beta_stability") > first_finite("market_residual_return")


def test_residual_of_spy_is_all_nan():
    spy = _bars(_walk(60, 2))
    records = build_market_residual_series(spy, spy, "SPY", CONFIG)
    assert all(math.isnan(v) for r in records.values() for v in r)


def test_residual_ignores_a_date_the_name_has_no_bar_on():
    """A missing bar must not become a stale close and a fabricated 0.0 return."""
    name, spy = _walk(60, 1), _walk(60, 2)
    records = build_market_residual_series(_bars(name, skip={30}), _bars(spy), "ABC", CONFIG)
    assert (START + timedelta(days=30)).date() not in records


def test_distribution_ranges():
    records = build_distribution_series(_bars(_walk(80, 3)), CONFIG)
    finite = [r for r in records.values() if not math.isnan(r.max_drawdown)]
    assert finite
    assert all(0.0 <= r.max_drawdown <= 1.0 for r in finite)
    downside = [
        r.downside_deviation for r in records.values() if not math.isnan(r.downside_deviation)
    ]
    assert downside and all(v >= 0.0 for v in downside)


def test_reconciled_amounts_unknown_outside_coverage_and_none_without_coverage():
    dates = [(START + timedelta(days=i)).date() for i in range(10)]
    cover = (dates[3], dates[8])
    out = reconciled_amounts(dates, cover, {dates[5]: 0.5})
    assert math.isnan(out[dates[2]]) and math.isnan(out[dates[9]])
    assert out[dates[4]] == 0.0 and out[dates[5]] == 0.5
    assert all(math.isnan(v) for v in reconciled_amounts(dates, None, {}).values())


def test_reconciled_amounts_moves_an_ex_date_without_a_bar_to_the_next_bar():
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 5)]  # Jan 4 has no bar
    out = reconciled_amounts(dates, (dates[0], dates[-1]), {date(2024, 1, 4): 0.4})
    assert out[date(2024, 1, 5)] == 0.4 and out[date(2024, 1, 3)] == 0.0


def test_dividend_yield_is_nan_while_the_window_holds_an_unknown_date():
    bars = _bars([100.0] * 12)
    dates = [b["ts"].date() for b in bars]
    amounts = reconciled_amounts(dates, (dates[4], dates[-1]), {dates[6]: 1.0})
    series = build_dividend_yield_series(bars, amounts, CONFIG)
    assert math.isnan(series[dates[7]])  # window still holds the uncovered dates
    assert series[dates[9]] == 0.01  # window fully covered, one 1.0 event over close 100
