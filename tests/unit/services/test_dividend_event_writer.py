"""Dividend derivation from TRADES / ADJUSTED_LAST ratio steps (todo 428).

Synthetic series are built the way IBKR builds ADJUSTED_LAST: TRADES close times a cumulative
factor that multiplies in (1 - amount / prior close) for every ex-date after the day, then
rounded to the cent.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from services.dividend_event_writer import (
    Derivation,
    DividendEvent,
    derive_ibkr_events,
    derive_yahoo_events,
    disagreeing_yields,
    join_adjustment_pairs,
    reconcile,
    vanished_ex_dates,
)

MARGIN = 1.25
STABLE = 3


def _series(closes, dividends):
    """dividends: {row index of ex-date: amount}. Returns (day, close, adjusted) rows."""
    n = len(closes)
    factor = np.ones(n)
    for i, amount in dividends.items():
        factor[:i] *= 1.0 - amount / closes[i - 1]
    start = date(2010, 1, 4)
    return [
        (start + timedelta(days=k), float(closes[k]), round(float(closes[k] * factor[k]), 2))
        for k in range(n)
    ]


def _walk(n, start_price, seed):
    rng = np.random.default_rng(seed)
    return np.round(start_price * np.exp(np.cumsum(rng.normal(0, 0.012, n))), 2)


def test_quarterly_dividends_recovered_within_rounding():
    closes = _walk(400, 470.0, seed=1)
    dividends = {60: 1.91, 123: 1.60, 186: 1.76, 249: 1.74, 312: 1.97}
    d = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    assert [e.ex_date for e in d.events] == [
        date(2010, 1, 4) + timedelta(days=i) for i in dividends
    ]
    for e, amount in zip(d.events, dividends.values(), strict=True):
        assert abs(e.dividend_yield - amount / e.prev_close) <= e.yield_tolerance
    assert (d.n_downward_steps, d.n_unstable_steps) == (0, 0)


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("price", [4.0, 75.0, 600.0])
def test_rounding_alone_never_produces_an_event(seed, price):
    # A deep cumulative factor (0.3) makes the adjusted prices small, the hardest case.
    closes = _walk(1500, price, seed)
    series = [(d, c, round(c * 0.3, 2)) for d, c, _ in _series(closes, {})]
    d = derive_ibkr_events(series, 1.0, STABLE)
    assert d.events == [] and d.n_downward_steps == 0 and d.n_unstable_steps == 0


def test_monthly_high_yield_payer_fully_recovered():
    closes = _walk(2000, 75.0, seed=7)
    dividends = {i: 0.38 for i in range(21, 1990, 21)}
    d = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    assert len(d.events) == len(dividends)
    assert all(abs(e.dividend_yield - 0.38 / e.prev_close) <= e.yield_tolerance for e in d.events)


def test_downward_step_is_an_anomaly_not_a_dividend():
    closes = _walk(50, 100.0, seed=3)
    series = _series(closes, {})
    series = series[:25] + [(day, c, round(a * 0.99, 2)) for day, c, a in series[25:]]
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == [] and d.n_downward_steps == 1


def test_one_day_excursion_is_unstable():
    closes = _walk(50, 100.0, seed=4)
    series = _series(closes, {})
    day, c, a = series[25]
    series[25] = (day, c, round(a * 1.01, 2))
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == [] and d.n_unstable_steps == 1 and d.n_downward_steps == 1


def test_newest_step_waits_for_the_next_run():
    closes = _walk(30, 100.0, seed=5)
    series = _series(closes, {29: 1.0})
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == []
    assert (d.covered_from, d.covered_to) == (series[1 + STABLE][0], series[-1 - STABLE][0])


def test_short_and_invalid_input():
    with pytest.raises(ValueError, match="too few"):
        derive_ibkr_events([], MARGIN, STABLE)
    with pytest.raises(ValueError, match="too few"):
        derive_yahoo_events([(date(2020, 1, 1), 10.0, 0.0)])
    with pytest.raises(ValueError, match="non-positive"):
        derive_ibkr_events([(date(2020, 1, 1), 0.0, 1.0)] * 10, MARGIN, STABLE)
    nan = float("nan")
    with pytest.raises(ValueError, match="unusable close"):
        derive_yahoo_events([(date(2020, 1, 1), 10.0, 0.0), (date(2020, 1, 2), nan, 0.2)])
    with pytest.raises(ValueError, match="unusable close"):  # the close a yield is taken from
        derive_yahoo_events(
            [(D, 10.0, 0), (D + timedelta(1), nan, 0), (D + timedelta(2), 9.0, 0.2)]
        )
    with pytest.raises(ValueError, match="unusable close"):
        derive_yahoo_events([(D, 10.0, 0.0), (D + timedelta(1), -1.0, 0.0)])
    # An untraded day away from any dividend is dropped, not fatal.
    d = derive_yahoo_events(
        [
            (D, 10.0, 0),
            (D + timedelta(1), nan, 0),
            (D + timedelta(2), 9.0, 0),
            (D + timedelta(3), 9.5, 0.2),
        ]
    )
    assert [(e.ex_date, e.prev_close) for e in d.events] == [(D + timedelta(3), 9.0)]
    with pytest.raises(ValueError, match="negative dividend"):
        derive_yahoo_events([(date(2020, 1, 1), 10.0, 0.0), (date(2020, 1, 2), 10.0, -0.1)])


def test_yahoo_events_use_the_prior_close_and_skip_row_zero():
    d0 = date(2020, 1, 2)
    rows = [(d0, 100.0, 0.5), (d0 + timedelta(1), 101.0, 0.0), (d0 + timedelta(2), 99.0, 0.8)]
    d = derive_yahoo_events(rows)
    assert [(e.ex_date, e.amount, e.prev_close) for e in d.events] == [(rows[2][0], 0.8, 101.0)]
    assert (d.covered_from, d.covered_to) == (rows[1][0], rows[2][0])


def test_rederived_yield_is_split_invariant():
    event = DividendEvent(date(2020, 3, 20), amount=1.80, prev_close=600.0, yield_tolerance=1e-5)
    derivation = Derivation([event], event.ex_date, event.ex_date)
    # Stored before a 2:1 split: amount 3.60 on a 1200 close, same yield.
    assert disagreeing_yields({event.ex_date: 3.60 / 1200.0}, derivation) == []
    assert disagreeing_yields({event.ex_date: 2.00 / 600.0}, derivation) == [event.ex_date]


D = date(2012, 10, 1)


def test_reconcile_flags_one_dividend_on_two_dates():
    rec = reconcile({D: 0.005}, {D + timedelta(1): 0.005}, (D, D), (D, D + timedelta(9)), 5, 0.1)
    assert rec.near_misses == [(D, D + timedelta(1))]
    assert rec.ibkr_holes == [] and rec.yahoo_holes == []


def test_reconcile_holes_count_only_inside_the_other_sources_span():
    later = D + timedelta(31)
    span = (D, later)
    rec = reconcile({D: 0.005}, {later: 0.005}, span, span, 5, 0.1)
    assert rec.near_misses == [] and rec.ibkr_holes == [later] and rec.yahoo_holes == [D]
    rec = reconcile({}, {later: 0.005}, (D, D), span, 5, 0.1)
    assert rec.ibkr_holes == []  # IBKR never examined that date


def test_reconcile_yield_disagreement_is_relative():
    assert reconcile({D: 0.0052}, {D: 0.005}, None, None, 5, 0.1).yield_disagreements == []
    assert reconcile({D: 0.0060}, {D: 0.005}, None, None, 5, 0.1).yield_disagreements == [D]


def test_join_refuses_a_day_missing_from_one_series():
    d = [date(2020, 1, k) for k in range(2, 7)]
    trades = {x: 10.0 for x in d}
    adjusted = {x: 9.0 for x in d}
    assert len(join_adjustment_pairs(trades, adjusted)) == 5
    # Different history depths are fine; only the overlap must match.
    assert len(join_adjustment_pairs(trades, {x: 9.0 for x in d[1:]})) == 4
    del adjusted[d[2]]
    with pytest.raises(ValueError, match="disagree on 1 days"):
        join_adjustment_pairs(trades, adjusted)


def test_vanished_ex_dates_only_inside_the_examined_span():
    event = DividendEvent(D + timedelta(1), 0.5, 100.0, 1e-6)
    derivation = Derivation([event], D, D + timedelta(20))
    stored = {D, D + timedelta(1), D + timedelta(40)}
    assert vanished_ex_dates(stored, derivation) == [D]


def test_yahoo_tolerance_absorbs_split_rerounding():
    # A 10:1 split re-scales and re-rounds: 0.52 on 41.37 becomes 0.052 on 4.14 (cents).
    event = derive_yahoo_events([(D, 41.40, 0.0), (D + timedelta(1), 41.37, 0.52)]).events[0]
    assert abs(0.052 / 4.14 - event.dividend_yield) <= event.yield_tolerance


@pytest.mark.parametrize("seed", range(10))
def test_series_on_different_closes_produce_no_events(seed):
    """NVR 2004: IBKR's two series used different closing prices, so the ratio wandered about
    0.3% a day, up to 150x the rounding bound. No step is stable; none may become a dividend."""
    rng = np.random.default_rng(seed)
    closes = _walk(500, 450.0, seed)
    other = closes * (1 + rng.uniform(-0.003, 0.003, len(closes)))
    series = [
        (d, c, round(float(a), 2)) for (d, c, _), a in zip(_series(closes, {}), other, strict=True)
    ]
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == [] and d.n_unstable_steps > 0


def test_weekly_payer_is_still_detected():
    closes = _walk(300, 25.0, seed=11)
    dividends = {i: 0.05 for i in range(10, 290, 5)}
    d = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    assert [e.ex_date for e in d.events] == [
        date(2010, 1, 4) + timedelta(days=i) for i in dividends
    ]
