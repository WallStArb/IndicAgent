"""Tests for the promoted cost-band module (scripts/research/cost_hurdle.py, plan 186-04).

The exact-equality checks against the originals under scripts/analysis/ are guarded with
importorskip so this file keeps passing after 186-16 deletes that directory; the same
equalities are asserted against inline formulas, which do not depend on the originals.
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from scripts.research import cost_hurdle


def test_constants_match_the_preregistration() -> None:
    assert cost_hurdle.SIGMA_TARGET == 0.16
    assert cost_hurdle.COMMISSION_PER_SHARE == 0.0035
    assert cost_hurdle.ASSUMED_PRICE == 50.0
    assert (
        cost_hurdle.COMMISSION_FRAC == cost_hurdle.COMMISSION_PER_SHARE / cost_hurdle.ASSUMED_PRICE
    )
    assert cost_hurdle.COMMISSION_FRAC == 0.0035 / 50.0
    assert cost_hurdle.LIVE_SPREAD_ANCHOR == 0.00014
    assert cost_hurdle.TRADING_DAYS_PER_YEAR == 252
    assert cost_hurdle.CS_VALIDATION_BAND == (0.5, 3.0)
    assert cost_hurdle.SPREAD_SENSITIVITY_BAND == (0.5, 1.0, 2.0)
    assert cost_hurdle.UNIVERSE_BREADTHS == (4.5, 8.4)
    assert cost_hurdle.LIBRARY_RANKS == (3.0, 10.0)


def _random_high_low(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    low = 100.0 * rng.random(n) + 1.0
    high = low + rng.random(n)
    return high, low


def test_corwin_schultz_daily_properties() -> None:
    rng = np.random.default_rng(42)
    high, low = _random_high_low(rng, 500)
    out = cost_hurdle.corwin_schultz_daily(high, low)
    assert len(out) == len(high) - 1
    assert (out >= 0).all()
    # Inline recomputation of the pre-registered estimator (does not need the original).
    log_hl = np.log(np.maximum(high, 1e-10) / np.maximum(low, 1e-10))
    beta = log_hl**2 + np.roll(log_hl, 1) ** 2
    beta[0] = log_hl[0] ** 2
    h2 = np.maximum(high, np.roll(high, 1))
    l2 = np.minimum(low, np.roll(low, 1))
    gamma = np.log(np.maximum(h2, 1e-10) / np.maximum(l2, 1e-10)) ** 2
    gamma[0] = log_hl[0] ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    assert np.array_equal(out, np.clip(spread, 0.0, None)[1:])


def test_corwin_schultz_daily_equals_original() -> None:
    original = pytest.importorskip("scripts.analysis.personal_cost_hurdle")
    rng = np.random.default_rng(7)
    high, low = _random_high_low(rng, 500)
    assert np.array_equal(
        cost_hurdle.corwin_schultz_daily(high, low),
        original._corwin_schultz_daily(high, low),
    )


def test_rank_turnover_guards() -> None:
    rng = np.random.default_rng(3)
    ranks = pd.DataFrame(rng.random((20, 4)), columns=list("ABCD"))
    # len(ranks) <= horizon + 5 -> None (20 <= 15 + 5 here).
    assert cost_hurdle.rank_turnover(ranks, 15) is None
    assert cost_hurdle.rank_turnover(ranks, 20) is None
    # An all-NaN frame with enough rows yields no usable values -> None.
    nan_frame = pd.DataFrame(np.nan, index=range(30), columns=list("ABCD"))
    assert cost_hurdle.rank_turnover(nan_frame, 1) is None


def test_rank_turnover_matches_inline_formula() -> None:
    rng = np.random.default_rng(11)
    ranks = pd.DataFrame(rng.random((60, 5)), columns=list("ABCDE"))
    ranks.iloc[3, 2] = np.nan
    ranks.iloc[10, 0] = np.nan
    for horizon in (1, 2, 5, 10):
        got = cost_hurdle.rank_turnover(ranks, horizon)
        diff = (ranks - ranks.shift(horizon)).abs()
        vals = diff.dropna(how="all").to_numpy().ravel()
        vals = vals[~np.isnan(vals)]
        assert got == float(vals.mean())


def test_rank_turnover_equals_originals() -> None:
    one_d = pytest.importorskip("scripts.analysis.personal_cost_hurdle")
    by_tf = pytest.importorskip("scripts.analysis.personal_cost_hurdle_by_tf")
    rng = np.random.default_rng(23)
    ranks = pd.DataFrame(rng.random((60, 5)), columns=list("ABCDE"))
    ranks.iloc[7, 4] = np.nan
    for horizon in (1, 2, 5, 10):
        got = cost_hurdle.rank_turnover(ranks, horizon)
        assert got == one_d._turnover(ranks, horizon)
        assert got == by_tf._turnover(ranks, horizon)


def test_one_way_cost() -> None:
    for spread in (0.0, 0.0001, 0.00014, 0.001, 0.0028):
        assert cost_hurdle.one_way_cost(spread) == spread / 2 + cost_hurdle.COMMISSION_FRAC
    assert cost_hurdle.one_way_cost(0.0028, commission_frac=0.0) == 0.0028 / 2


def test_annual_drag_operation_order() -> None:
    to = 0.16
    one_way = cost_hurdle.one_way_cost(0.0014)
    for h in (1, 2, 5, 10):
        assert cost_hurdle.annual_drag(252 / h, to, one_way) == (252 / h) * 2 * to * one_way
    # The by-tf original annualizes with bars_per_year / h; same operation order.
    bars_per_year = 252 * 26.0
    for h in (1, 6, 12, 39):
        assert (
            cost_hurdle.annual_drag(bars_per_year / h, to, one_way)
            == (bars_per_year / h) * 2 * to * one_way
        )


def test_ic_min_formula() -> None:
    drag = 0.0023
    for bets in (3.0 * 4.5, 3.0 * 8.4, 10.0 * 4.5, 10.0 * 8.4):
        assert cost_hurdle.ic_min(drag, bets) == drag / (0.16 * np.sqrt(bets))
    assert cost_hurdle.ic_min(drag, 27.0, sigma=0.2) == drag / (0.2 * np.sqrt(27.0))


def _symbol_rows(symbol: str, n: int, rng: np.random.Generator) -> list[tuple]:
    low = np.cumsum(rng.standard_normal(n) * 0.1) + 100.0
    high = low + rng.random(n) + 0.01
    ts = pd.date_range("2024-01-01", periods=n, freq="D")
    return [(symbol, t, float(h), float(lo)) for t, h, lo in zip(ts, high, low)]


def test_estimate_cs_spreads_drops_short_symbols() -> None:
    rng = np.random.default_rng(9)
    rows = _symbol_rows("KEEP", 300, rng) + _symbol_rows("DROP", 100, rng)
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    out = cost_hurdle.estimate_cs_spreads(conn)

    assert isinstance(out, pd.Series)
    assert list(out.index) == ["KEEP"]
    keep_rows = sorted((r for r in rows if r[0] == "KEEP"), key=lambda r: r[1])
    expected = float(
        np.mean(
            cost_hurdle.corwin_schultz_daily(
                np.array([r[2] for r in keep_rows]), np.array([r[3] for r in keep_rows])
            )
        )
    )
    assert out["KEEP"] == expected
    # The lookback interval is a bound parameter cast to interval, never formatted into SQL.
    sql, params = cursor.execute.call_args.args
    assert "%s::interval" in sql
    assert "market_data_ohlcv_tradeable" in sql
    assert params == ("2 years",)


def test_estimate_cs_spreads_parameters_are_real() -> None:
    rng = np.random.default_rng(13)
    rows = _symbol_rows("KEEP", 300, rng) + _symbol_rows("DROP", 100, rng)
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    out = cost_hurdle.estimate_cs_spreads(conn, lookback="5 years", min_bars=50)

    assert sorted(out.index) == ["DROP", "KEEP"]
    sql, params = cursor.execute.call_args.args
    assert params == ("5 years",)


def test_cost_hurdle_module_imports_nothing_heavy() -> None:
    code = (
        "import sys; "
        "import scripts.research.cost_hurdle; "
        "bad = [m for m in ('services.backfill_feature_factory', 'src.providers.ibkr', "
        "'src.intelligence.research') "
        "if m in sys.modules or any(k.startswith(m + '.') for k in sys.modules)]; "
        "print(bad)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
